"""
DOCSREG → master document writer (Omi + Qdrant).

Three-step registration for every certified master document:
  1. Copy file → aims_workspace/master/P{XX}_{Name}/
  2. Register via StorageManager.register_generated_bundle() → documents SQLite table
  3. Embed text chunks with nomic-embed-text, upsert to Qdrant aims_docs collection

Search is via Qdrant (semantic), not SQLite FTS5.

Exported:
    write_master_document(...)  — idempotent three-step registration
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("docsreg_db_writer")

# ── Environment defaults ──────────────────────────────────────────────────────

_WORKSPACE_ROOT = Path(
    os.environ.get("AIMS_WORKSPACE")
    or os.environ.get("OMI_DATA_ROOT")
    or str(Path(__file__).resolve().parents[2] / "aims_workspace")
)
_MASTER_DIR = Path(
    os.environ.get("AXI_MASTER_DOCUMENTS_PATH", str(_WORKSPACE_ROOT / "master"))
)
_DB_PATH = Path(
    os.environ.get(
        "AIMS_REGISTRY_DB",
        str(Path(__file__).resolve().parents[2] / "data" / "aims_registry.db"),
    )
)
_QDRANT_URL = os.environ.get("OMI_QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
_QDRANT_COLLECTION = os.environ.get("OMI_QDRANT_COLLECTION", "aims_docs")
# Use direct localhost for embeddings (not host.docker.internal — this runs on host)
_OLLAMA_URL = (
    os.environ.get("OLLAMA_LOCAL_URL", "")
    .replace("host.docker.internal", "127.0.0.1")
    .rstrip("/")
    or "http://127.0.0.1:11434"
)
_EMBED_MODEL = "nomic-embed-text"
_EMBED_DIM = 768
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150


# ── P-code mapping ────────────────────────────────────────────────────────────

# (keywords in doc_type) → P-code folder under master/
_PCODE_MAP: list[tuple[tuple[str, ...], str]] = [
    (("asset_strategy", "strategy"), "P01_Asset_Strategy"),
    (("risk",), "P02_Risk_Assessment"),
    (("inspection_plan",), "P03_Inspection_Planning"),
    (("inspection",), "P04_Inspection_Execution"),
    (("maintenance_strategy",), "P05_Maintenance_Strategy"),
    (("maintenance", "procedure", "repair"), "P06_Maintenance_Execution"),
    (("sce", "safety_critical", "performance"), "P07_SCE_Performance"),
    (("moc", "change"), "P08_MoC_Management"),
    (("report", "kpi", "metric"), "P09_Reporting_KPI"),
    (("competence", "training"), "P10_Competence_Training"),
    (("pcv", "cv"), "P11_PCV"),
]


def _resolve_pcode_folder(doc_type: str) -> str:
    """Return the master/ subfolder for a given document type."""
    key = doc_type.lower().replace("-", "_").replace(" ", "_")
    for keywords, folder in _PCODE_MAP:
        if any(k in key for k in keywords):
            return folder
    return "P01_Asset_Strategy"


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def _ensure_qdrant_collection() -> None:
    """Create aims_docs Qdrant collection if absent (768-dim Cosine)."""
    url = f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return
        requests.put(
            url,
            json={"vectors": {"size": _EMBED_DIM, "distance": "Cosine"}},
            timeout=10,
        ).raise_for_status()
        log.info("docsreg_db_writer: created Qdrant collection %s", _QDRANT_COLLECTION)
    except Exception as exc:
        log.warning("docsreg_db_writer: Qdrant collection init failed: %s", exc)


def _embed(text: str) -> list[float] | None:
    """Return 768-dim embedding from nomic-embed-text via Ollama."""
    try:
        r = requests.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": text},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception as exc:
        log.warning("docsreg_db_writer: embed error: %s", exc)
        return None


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks for Qdrant upsert."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + _CHUNK_SIZE])
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _upsert_to_qdrant(
    *,
    doc_id: str,
    title: str,
    doc_type: str,
    file_path: str,
    text: str,
    quality_score: float,
    run_id: str,
    aims_process: str,
) -> int:
    """Embed document chunks and upsert them to Qdrant aims_docs. Returns point count."""
    _ensure_qdrant_collection()
    chunks = _chunk_text(text) or [title]
    points: list[dict] = []
    for i, chunk in enumerate(chunks):
        vec = _embed(chunk)
        if vec is None:
            continue
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:chunk:{i}"))
        points.append(
            {
                "id": point_id,
                "vector": vec,
                "payload": {
                    "doc_id": doc_id,
                    "title": title,
                    "doc_type": doc_type,
                    "aims_process": aims_process,
                    "file_path": file_path,
                    "quality_score": quality_score,
                    "docsreg_run_id": run_id,
                    "chunk_index": i,
                    "chunk_total": len(chunks),
                    "content": chunk,
                },
            }
        )

    if not points:
        log.warning("docsreg_db_writer: no embeddings generated for doc_id=%s", doc_id)
        return 0

    try:
        requests.put(
            f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}/points",
            json={"points": points},
            timeout=60,
        ).raise_for_status()
        log.info(
            "docsreg_db_writer: upserted %d Qdrant points for doc_id=%s",
            len(points), doc_id,
        )
    except Exception as exc:
        log.error("docsreg_db_writer: Qdrant upsert failed for doc_id=%s: %s", doc_id, exc)
        return 0

    return len(points)


# ── Master document writer ────────────────────────────────────────────────────

def write_master_document(
    *,
    document_id: str | None = None,
    title: str,
    doc_type: str,
    file_path: str,
    content: str = "",
    quality_score: float = 0.0,
    certification_status: str = "CERTIFIED",
    master_doc_json: str | None = None,
    run_id: str = "",
    metadata: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Register a certified master document: copy → Omi SQLite → Qdrant.

    Parameters
    ----------
    document_id:
        Stable doc ID.  Generated as UUID if *None*.
    title:
        Human-readable document title.
    doc_type:
        Document category — used to resolve P-code subfolder.
    file_path:
        Path to the certified source file (DOCX or text).
    content:
        Full document text for Qdrant embedding.
    quality_score:
        Aggregate quality score in [0.0, 1.0].
    certification_status:
        One of "CERTIFIED", "PENDING", "REJECTED".
    master_doc_json:
        Full RegistrationRecord JSON string from DOCSREG certification.
        Written to the ``master_doc_json`` column in the documents table.
        If *None*, the column is left as-is (UPDATE) or NULL (INSERT).
    run_id:
        DOCSREG run identifier.
    metadata:
        Ignored (kept for API compatibility — metadata goes via Omi notes).
    db_path:
        Override the default aims_registry.db path.

    Returns
    -------
    str
        The document_id used.
    """
    doc_id = document_id or str(uuid.uuid4())
    source = Path(file_path)
    pcode_folder = _resolve_pcode_folder(doc_type)
    aims_process = pcode_folder.split("_")[0]  # "P06" etc.

    # ── Step 1: copy to master directory ─────────────────────────────────────
    target_dir = _MASTER_DIR / pcode_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    master_path = target_dir / source.name
    try:
        if source.is_file() and source.resolve() != master_path.resolve():
            shutil.copy2(str(source), str(master_path))
            log.info("docsreg_db_writer: copied %s → %s", source.name, master_path)
        elif master_path.exists():
            log.debug("docsreg_db_writer: master copy already exists: %s", master_path)
        else:
            log.warning("docsreg_db_writer: source file not found: %s", source)
            master_path = source  # best-effort: reference original
    except Exception as exc:
        log.error("docsreg_db_writer: copy to master failed: %s", exc)
        master_path = source

    # ── Step 2: register via Omi StorageManager ───────────────────────────────
    sqlite_ok = False
    try:
        from ops.omi_telegram.omi_storage import StorageManager  # noqa: PLC0415

        db = Path(db_path) if db_path else _DB_PATH
        # StorageManager workspace must be a parent of master_path
        # aims_workspace/ is the parent of master/
        sm = StorageManager(db_path=db, workspace=_MASTER_DIR.parent)
        result = sm.register_generated_bundle(
            str(master_path),
            aims_process=aims_process,
            master_doc_json=master_doc_json,
        )
        log.info("docsreg_db_writer: Omi registration → %s", result)
        sqlite_ok = True
    except Exception as exc:
        log.error(
            "docsreg_db_writer: Omi registration failed for %s: %s — Qdrant upsert skipped",
            doc_id, exc,
        )

    # ── Step 3: embed + upsert to Qdrant aims_docs ───────────────────────────
    # Only index in Qdrant if the authoritative SQLite row was written successfully.
    # This prevents orphaned Qdrant vectors that have no corresponding registry entry.
    if not sqlite_ok:
        log.warning(
            "docsreg_db_writer: skipping Qdrant upsert for doc_id=%s (SQLite write failed)",
            doc_id,
        )
    else:
        _upsert_to_qdrant(
            doc_id=doc_id,
            title=title or source.stem,
            doc_type=doc_type,
            file_path=str(master_path),
            text=content,
            quality_score=quality_score,
            run_id=run_id,
            aims_process=aims_process,
        )

    log.info(
        "docsreg_db_writer: DONE doc_id=%s pcode=%s cert=%s score=%.3f",
        doc_id, aims_process, certification_status, quality_score,
    )
    return doc_id
