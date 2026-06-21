"""Pipeline runner: extract, validate, align, and register a classification standard."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from ..alignment.record_aligner import RecordAligner
from ..anonymization.metadata_cleaner import MetadataCleaner
from ..anonymization.text_sanitizer import TextSanitizer
from ..registration_package.builder import RegistrationPackageBuilder
from ..table_reconstruction.abs_notation_extractor import ABSNotationExtractor
from ..table_reconstruction.models import SourcePage
from ..table_reconstruction.page_classifier import build_source_page
from ..table_reconstruction.symbol_normalization_pass import SymbolNormalizationPass

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    standard_id: str
    source_file: str
    output_dir: Path
    total_pages: int
    total_records: int
    total_chunks: int
    validation_passed: bool
    alignment_verdict: str
    data_retention: float
    success: bool
    error: str | None = None


def slugify(name: str) -> str:
    """Convert filename to standard_id slug."""
    stem = Path(name).stem
    slug = stem.replace(" ", "_").replace("-", "_")
    # Remove non-alphanum/underscore
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    return slug.lower()


def extract_pages_from_pdf(pdf_path: Path) -> list[SourcePage]:
    """Extract text pages from a PDF using pdfplumber."""
    pages: list[SourcePage] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append(build_source_page(i, text))
    return pages


def run_pipeline(
    pdf_path: Path,
    output_root: Path,
    standard_id: str | None = None,
) -> PipelineResult:
    """Run the full classification standard registration pipeline.

    Steps:
      1. Extract text pages from PDF (pdfplumber)
      2. Sanitize + anonymize text
      3. Extract classification records (ABSNotationExtractor)
      4. Normalize symbols (SymbolNormalizationPass)
      5. Align source vs. master (RecordAligner)
      6. Build registration package (RegistrationPackageBuilder)

    Returns:
      PipelineResult with output directory and quality metrics.
    """
    pdf_path = Path(pdf_path)
    output_root = Path(output_root)

    if standard_id is None:
        standard_id = slugify(pdf_path.name)

    logger.info("Pipeline START: %s → %s", pdf_path.name, standard_id)

    try:
        # Step 1: Extract pages
        pages = extract_pages_from_pdf(pdf_path)
        logger.info("Extracted %d pages from %s", len(pages), pdf_path.name)

        if not pages:
            return PipelineResult(
                standard_id=standard_id,
                source_file=pdf_path.name,
                output_dir=output_root / standard_id,
                total_pages=0, total_records=0, total_chunks=0,
                validation_passed=False,
                alignment_verdict="FAIL",
                data_retention=0.0,
                success=False,
                error="No pages extracted from PDF.",
            )

        # Step 2: Sanitize + anonymize
        sanitizer = TextSanitizer()
        cleaner = MetadataCleaner()

        sanitized_pages: list[SourcePage] = []
        all_redactions: list[str] = []
        for page in pages:
            clean_text = sanitizer.sanitize(page.text)
            clean_text, redactions = cleaner.clean(clean_text)
            all_redactions.extend(redactions)
            sanitized_pages.append(SourcePage(
                page_index=page.page_index,
                abs_page_number=page.abs_page_number,
                text=clean_text,
                image_path=page.image_path,
            ))

        if all_redactions:
            logger.info("Redacted %d sensitive items", len(all_redactions))

        # Build raw text for the package
        raw_text = "\n\n---\n\n".join(
            f"<!-- Page {p.page_index + 1} -->\n{p.text}" for p in sanitized_pages
        )

        # Step 3: Extract classification records
        extractor = ABSNotationExtractor(standard_id)
        records = extractor.extract_from_pages(sanitized_pages)
        logger.info("Extracted %d classification records", len(records))

        # Step 4: Normalize symbols
        normalizer = SymbolNormalizationPass()
        records = normalizer.apply(records)

        # Step 5: Align source vs. master
        aligner = RecordAligner()
        alignment = aligner.align(standard_id, sanitized_pages, records)
        logger.info(
            "Alignment: retention=%.2f%%, verdict=%s",
            alignment.data_retention_ratio * 100,
            alignment.verdict.value,
        )

        # Step 6: Build registration package
        builder = RegistrationPackageBuilder(output_root)
        output_dir = builder.build(
            standard_id=standard_id,
            source_file=pdf_path.name,
            source_pages=sanitized_pages,
            records=records,
            raw_text=raw_text,
            alignment_report=alignment,
        )

        # Count chunks from the chunks file
        chunks_file = output_dir / "chunks.jsonl"
        chunk_count = sum(1 for _ in chunks_file.open()) if chunks_file.exists() else 0

        result = PipelineResult(
            standard_id=standard_id,
            source_file=pdf_path.name,
            output_dir=output_dir,
            total_pages=len(pages),
            total_records=len(records),
            total_chunks=chunk_count,
            validation_passed=alignment.passed,
            alignment_verdict=alignment.verdict.value,
            data_retention=alignment.data_retention_ratio,
            success=True,
        )

        logger.info(
            "Pipeline COMPLETE: %s — %d records, %d chunks, verdict=%s",
            standard_id, len(records), chunk_count, alignment.verdict.value,
        )

        return result

    except Exception as e:
        logger.exception("Pipeline FAILED for %s", pdf_path.name)
        return PipelineResult(
            standard_id=standard_id,
            source_file=pdf_path.name,
            output_dir=output_root / standard_id,
            total_pages=0, total_records=0, total_chunks=0,
            validation_passed=False,
            alignment_verdict="FAIL",
            data_retention=0.0,
            success=False,
            error=str(e),
        )


def run_batch(
    pdf_dir: Path,
    output_root: Path,
) -> list[PipelineResult]:
    """Run the pipeline on all PDFs in a directory."""
    pdf_dir = Path(pdf_dir)
    output_root = Path(output_root)
    results: list[PipelineResult] = []

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    logger.info("Batch: found %d PDF files in %s", len(pdf_files), pdf_dir)

    for pdf_path in pdf_files:
        result = run_pipeline(pdf_path, output_root)
        results.append(result)

    return results
