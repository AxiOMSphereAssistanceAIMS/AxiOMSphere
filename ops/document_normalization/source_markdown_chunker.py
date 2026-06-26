from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class MarkdownChunk:
    chunk_id: str
    source_id: str
    chunk_type: str
    heading_path: list[str]
    markdown: str
    line_start: int
    line_end: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_markdown(markdown: str, *, source_id: str) -> list[MarkdownChunk]:
    """Chunk markdown into stable, line-based chunks.

    The chunker is intentionally conservative: it preserves line ranges and
    keeps headings, tables, lists, and paragraphs separable enough for RAG and
    evidence mapping without attempting aggressive semantic rewriting.
    """
    text = markdown or ""
    if not text.strip():
        return []

    lines = text.splitlines()
    chunks: list[MarkdownChunk] = []
    heading_path: list[str] = []
    current: list[str] = []
    current_type = "paragraph"
    current_start = 1

    def flush(end_line: int) -> None:
        nonlocal current, current_type, current_start
        if not current:
            return
        body = "\n".join(current).rstrip()
        if not body.strip():
            current = []
            return
        chunk_index = len(chunks) + 1
        chunks.append(
            MarkdownChunk(
                chunk_id=f"{source_id}-CH-{chunk_index:04d}",
                source_id=source_id,
                chunk_type=current_type,
                heading_path=list(heading_path),
                markdown=body,
                line_start=current_start,
                line_end=end_line,
                sha256=_sha256_text(body),
            )
        )
        current = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            flush(lineno - 1)
            depth = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped[depth:].strip()
            heading_path[:] = heading_path[: max(depth - 1, 0)]
            if heading_text:
                heading_path.append(heading_text)
            current = [line]
            current_start = lineno
            current_type = "heading"
            flush(lineno)
            current_type = "paragraph"
            current_start = lineno + 1
            continue

        if "|" in line and stripped and not stripped.startswith("```"):
            if current and current_type != "table":
                flush(lineno - 1)
            if not current:
                current_start = lineno
            current_type = "table"
        elif stripped.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            if current and current_type not in {"list", "table"}:
                flush(lineno - 1)
            if not current:
                current_start = lineno
            current_type = "list"
        elif not stripped:
            if current:
                flush(lineno - 1)
            current_type = "paragraph"
            current_start = lineno + 1
            continue
        else:
            if current and current_type not in {"paragraph", "mixed"}:
                flush(lineno - 1)
            if not current:
                current_start = lineno
            if current_type not in {"table", "list", "heading"}:
                current_type = "paragraph"

        current.append(line)

    flush(len(lines))
    return chunks
