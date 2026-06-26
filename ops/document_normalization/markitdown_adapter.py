from __future__ import annotations

import importlib
import json
import os
import sys
import traceback
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from ops.document_normalization.extraction_models import ExtractionResult, make_extraction_result

from .source_markdown_chunker import chunk_markdown

MARKITDOWN_SUPPORTED_SUFFIXES = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xls",
        ".csv",
        ".html",
        ".htm",
        ".txt",
        ".md",
    }
)


def _markitdown_version(module: Any) -> str:
    try:
        return importlib_metadata.version("markitdown")
    except Exception:
        return str(getattr(module, "__version__", "unknown"))


def _candidate_markitdown_site_packages() -> list[Path]:
    configured = [
        item
        for value in (
            os.environ.get("AIMS_MARKITDOWN_SITE_PACKAGES", ""),
            os.environ.get("DOCSREG_MARKITDOWN_SITE_PACKAGES", ""),
        )
        for item in value.split(os.pathsep)
        if item.strip()
    ]
    candidates = [Path(item).expanduser() for item in configured]
    repo_root = Path(__file__).resolve().parents[2]
    for venv_name in (".venv-markitdown",):
        lib_root = repo_root / venv_name / "lib"
        if lib_root.exists():
            candidates.extend(sorted(lib_root.glob("python*/site-packages")))
    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            ordered.append(candidate)
    return ordered


def _import_markitdown() -> tuple[type[Any], Any]:
    module = importlib.import_module("markitdown")
    return getattr(module, "MarkItDown"), module


def _load_markitdown() -> tuple[type[Any] | None, str, str]:
    try:
        markitdown_class, module = _import_markitdown()
        return markitdown_class, _markitdown_version(module), ""
    except Exception as first_exc:
        fallback_errors: list[str] = [f"{first_exc.__class__.__name__}: {first_exc}"]

    attempted_paths: list[str] = []
    for site_packages in _candidate_markitdown_site_packages():
        if not site_packages.exists():
            continue
        site_packages_str = str(site_packages)
        attempted_paths.append(site_packages_str)
        if site_packages_str not in sys.path:
            sys.path.append(site_packages_str)
        try:
            markitdown_class, module = _import_markitdown()
            return markitdown_class, _markitdown_version(module), ""
        except Exception as exc:
            fallback_errors.append(f"{exc.__class__.__name__}: {exc}")

    detail = "; ".join(fallback_errors)
    if attempted_paths:
        detail = f"{detail}; attempted_site_packages={attempted_paths}"
    return None, "unavailable", detail


def _text_from_conversion(result: Any) -> str:
    for attr in ("text_content", "markdown", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(result, str):
        return result
    return ""


def extract_with_markitdown(source_path: Path) -> ExtractionResult:
    """Extract a source file to raw Markdown using Microsoft MarkItDown."""
    source = Path(source_path)
    suffix = source.suffix.lower()
    base_metadata = {
        "source_suffix": suffix,
        "supported_suffixes": sorted(MARKITDOWN_SUPPORTED_SUFFIXES),
    }

    if suffix not in MARKITDOWN_SUPPORTED_SUFFIXES:
        return make_extraction_result(
            source_path=str(source),
            extractor="markitdown",
            status="unsupported_format",
            warnings=[f"unsupported_format:{suffix or 'none'}"],
            metadata=base_metadata,
        )

    if not source.exists():
        return make_extraction_result(
            source_path=str(source),
            extractor="markitdown",
            status="extraction_failed",
            warnings=["source_file_not_found"],
            metadata=base_metadata,
        )

    markitdown_class, version, import_error = _load_markitdown()
    metadata = dict(base_metadata)
    metadata["markitdown_version"] = version
    if markitdown_class is None:
        return make_extraction_result(
            source_path=str(source),
            extractor="markitdown",
            status="extractor_unavailable",
            warnings=[f"extractor_unavailable:{import_error}"],
            metadata=metadata,
        )

    try:
        converter = markitdown_class()
        converted = converter.convert(str(source))
        raw_markdown = _text_from_conversion(converted)
    except Exception as exc:
        metadata["exception_class"] = exc.__class__.__name__
        return make_extraction_result(
            source_path=str(source),
            extractor="markitdown",
            status="extraction_failed",
            warnings=[
                f"extraction_failed:{exc.__class__.__name__}:{exc}",
                traceback.format_exc(),
            ],
            metadata=metadata,
        )

    if not raw_markdown.strip():
        return make_extraction_result(
            source_path=str(source),
            extractor="markitdown",
            status="extraction_failed",
            raw_markdown=raw_markdown,
            warnings=["empty_markdown_output"],
            metadata=metadata,
        )

    metadata["chunk_count_hint"] = len(chunk_markdown(raw_markdown, source_id=source.stem))
    return make_extraction_result(
        source_path=str(source),
        extractor="markitdown",
        status="extracted",
        raw_markdown=raw_markdown,
        metadata=metadata,
    )


def write_extraction_artifacts(
    result: ExtractionResult,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write raw extraction artifacts and return their paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_path = out / "raw_extracted_text.md"
    report_path = out / "extraction_report.json"
    normalized_path = out / "normalized_markdown.md"

    raw_path.write_text(result.raw_markdown or "", encoding="utf-8")
    normalized_path.write_text(result.raw_markdown or "", encoding="utf-8")

    report = result.to_dict()
    report["normalized_markdown_path"] = str(normalized_path)
    report["chunk_count"] = len(chunk_markdown(result.raw_markdown or "", source_id=Path(result.source_path).stem))
    report.pop("raw_markdown", None)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "raw_extracted_text": str(raw_path),
        "normalized_markdown": str(normalized_path),
        "extraction_report": str(report_path),
    }
