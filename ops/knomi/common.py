from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

COMPACT_CARD_KEYS = {
    "schema",
    "status",
    "session_id",
    "title",
    "kind",
    "content",
    "source_hashes",
    "verified_at_utc",
    "raw_transcript_included",
    "direct_training_allowed",
}
COMPACT_CONTENT_KEYS = {
    "lesson_id",
    "observed_problem",
    "root_cause",
    "prevention_rule",
    "reusable_lesson",
    "affected_component",
    "applicability_scope",
    "recommended_action",
    "failure_class",
    "disposition",
    "missing_file_count",
    "empty_file_count",
}
RAW_MARKERS = ("begin raw transcript", "full transcript", "\x1b[", "stdout.log:", "stderr.log:")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_compact_card(row: dict) -> tuple[bool, str]:
    if set(row) != COMPACT_CARD_KEYS:
        return False, "card keys do not match compact allowlist"
    if row.get("schema") not in {
        "aims.knomi.codex_lesson_card.v2",
        "aims.knomi.codex_capture_failure_card.v2",
    }:
        return False, "unknown compact card schema"
    if row.get("status") not in {"VALIDATED_COMPACT", "BENEFIT_VERIFIED"}:
        return False, "card is not compact-validated"
    if row.get("raw_transcript_included") is not False or row.get("direct_training_allowed") is not False:
        return False, "unsafe card flags"
    for key in ("session_id", "title", "kind"):
        value = row.get(key)
        if not isinstance(value, str) or not value or len(value) > 240 or any(marker in value.lower() for marker in RAW_MARKERS):
            return False, f"unsafe compact metadata: {key}"
    hashes = row.get("source_hashes")
    if not isinstance(hashes, dict) or not hashes or len(hashes) > 16 or any(
        not isinstance(key, str)
        or len(key) > 120
        or not key.endswith("_sha256")
        or not isinstance(value, str)
        or SHA256_RE.fullmatch(value) is None
        for key, value in hashes.items()
    ):
        return False, "source_hashes must contain only named SHA-256 digests"
    verified_at = row.get("verified_at_utc")
    if row.get("status") == "BENEFIT_VERIFIED":
        try:
            if datetime.fromisoformat(str(verified_at)).tzinfo is None:
                return False, "verified timestamp must be timezone-aware"
        except ValueError:
            return False, "verified timestamp missing or invalid"
    elif verified_at is not None:
        return False, "staged card cannot claim a verification timestamp"
    content = row.get("content")
    if not isinstance(content, dict) or not content or not set(content).issubset(COMPACT_CONTENT_KEYS):
        return False, "content keys do not match compact allowlist"
    for value in content.values():
        if isinstance(value, (int, float, bool)) or value is None:
            continue
        if not isinstance(value, str):
            return False, "compact values must be scalar"
        low = value.lower()
        if len(value) > 1200 or value.count("\n") > 8 or any(marker in low for marker in RAW_MARKERS):
            return False, "transcript-like or oversized compact value"
    if len(json.dumps(content, ensure_ascii=False)) > 6000:
        return False, "compact content exceeds size limit"
    if len(json.dumps(row, ensure_ascii=False)) > 10000:
        return False, "compact card exceeds total size limit"
    return True, "PASS"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    configured = Path(os.environ.get("AIMS_WORKSPACE", "/workspace")).expanduser()
    if configured.exists():
        return configured.resolve()
    # Fallback for local host runs outside container.
    return Path(__file__).resolve().parents[2]


def knowledge_root(explicit_workspace: Path | None = None) -> Path:
    if explicit_workspace is not None:
        return (explicit_workspace.resolve() / "aims_workspace/knowledge").resolve()
    raw = os.environ.get("KNOMI_KNOWLEDGE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (workspace_root() / "knowledge").resolve()


def ensure_knowledge_layout(explicit_workspace: Path | None = None) -> dict[str, Path]:
    root = knowledge_root(explicit_workspace)
    events = root / "events"
    decisions = root / "decisions"
    snapshots = root / "snapshots"
    index = root / "index"
    for p in (root, events, decisions, snapshots, index):
        p.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "events": events,
        "decisions": decisions,
        "snapshots": snapshots,
        "index": index,
    }


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def embed_text(text: str, model: str | None = None, base_url: str | None = None) -> list[float]:
    model_name = (model or os.environ.get("KNOMI_EMBED_MODEL", "nomic-embed-text")).strip() or "nomic-embed-text"
    # Priority: explicit arg > KNOMI_OLLAMA_URL > DGX_OLLAMA_URL >
    # OLLAMA_BASE_URL (compose contract) > OLLAMA_LOCAL_URL > localhost.
    # The compose service exports OLLAMA_BASE_URL; omitting it made the
    # container silently call its own localhost:11434 and return 500 when the
    # embedding model existed on the DGX host.
    # (OLLAMA_LOCAL_URL is docker-only; KNOMI_OLLAMA_URL lets host processes override it)
    base = (
        base_url
        or os.environ.get("KNOMI_OLLAMA_URL")
        or os.environ.get("DGX_OLLAMA_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_LOCAL_URL")
        or "http://127.0.0.1:11434"
    )
    base = base.strip().rstrip("/")
    r = httpx.post(
        f"{base}/api/embeddings",
        json={"model": model_name, "prompt": text},
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json()
    vec = data.get("embedding") or data.get("embeddings")
    if not isinstance(vec, list) or not vec:
        raise RuntimeError(f"invalid embedding response: {str(data)[:200]}")
    return [float(x) for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass
class Chunk:
    source: str
    kind: str
    title: str
    text: str
    ts: str


def iter_text_chunks(max_chars: int = 1200, *, explicit_workspace: Path | None = None) -> list[Chunk]:
    root = knowledge_root(explicit_workspace)
    paths = {
        "root": root,
        "events": root / "events",
        "decisions": root / "decisions",
        "snapshots": root / "snapshots",
        "index": root / "index",
    }
    out: list[Chunk] = []

    for p in sorted(paths["events"].glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            title = str(row.get("kind", "event"))
            text = json.dumps(row, ensure_ascii=False)
            out.append(
                Chunk(
                    source=str(p),
                    kind="event",
                    title=title,
                    text=text[:max_chars],
                    ts=str(row.get("ts") or row.get("timestamp") or ""),
                )
            )

    for p in sorted(paths["decisions"].glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for i in range(0, len(text), max_chars):
            piece = text[i : i + max_chars].strip()
            if not piece:
                continue
            out.append(
                Chunk(
                    source=str(p),
                    kind="decision",
                    title=p.name,
                    text=piece,
                    ts=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                )
            )

    for p in sorted(paths["snapshots"].glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for i in range(0, len(text), max_chars):
            piece = text[i : i + max_chars].strip()
            if not piece:
                continue
            out.append(
                Chunk(
                    source=str(p),
                    kind="snapshot",
                    title=p.name,
                    text=piece,
                    ts=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                )
            )

    # Codex raw transcripts are intentionally excluded.  Only compact lesson
    # cards that passed Logi traceability and downstream gates become Knomi
    # retrieval sources.
    lesson_root = paths["root"] / "codex_lessons"
    if lesson_root.exists():
        for p in sorted(lesson_root.glob("*.json")):
            try:
                row = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            valid, _reason = validate_compact_card(row)
            if not valid or row.get("status") != "BENEFIT_VERIFIED":
                continue
            text = json.dumps(row, ensure_ascii=False)
            out.append(
                Chunk(
                    source=str(p),
                    kind="codex_lesson",
                    title=str(row.get("title") or row.get("session_id") or p.stem),
                    text=text[:max_chars],
                    ts=str(row.get("verified_at_utc") or ""),
                )
            )

    # Include current policy and runtime docs from repository tree so policy-focused
    # queries return authoritative up-to-date files, not only historical knowledge/.
    policy_candidates = [
        workspace_root(explicit_workspace) / "docs" / "AIMS_FULLSTACK_INTEGRATION_STATUS.md",
        workspace_root(explicit_workspace) / "docs" / "AIMS_MODEL_ESCALATION_POLICY.md",
        workspace_root(explicit_workspace) / "ops" / "argus" / "service_lifecycle_policy.yaml",
        workspace_root(explicit_workspace) / "ops" / "evals" / "dgx_model_concurrency_policy_smoke.py",
        workspace_root(explicit_workspace) / "docs" / "agents" / "AIMS_FULLSTACK_AGENT_MAPPING.md",
    ]
    for p in policy_candidates:
        if not p.exists() or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for i in range(0, len(text), max_chars):
            piece = text[i : i + max_chars].strip()
            if not piece:
                continue
            out.append(
                Chunk(
                    source=str(p),
                    kind="policy",
                    title=p.name,
                    text=piece,
                    ts=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                )
            )
    return out


def index_db_path() -> Path:
    paths = ensure_knowledge_layout()
    return paths["index"] / "aims_knowledge_index.sqlite3"


def open_db() -> sqlite3.Connection:
    db = sqlite3.connect(index_db_path())
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            ts TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding_json TEXT NOT NULL
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_ts ON chunks(ts)")
    return db
