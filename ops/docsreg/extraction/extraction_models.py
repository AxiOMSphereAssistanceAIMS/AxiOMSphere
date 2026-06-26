from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    source_path: str
    extractor: str
    status: str
    raw_markdown: str
    word_count: int
    char_count: int
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_extraction_result(
    *,
    source_path: str,
    extractor: str,
    status: str,
    raw_markdown: str = "",
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExtractionResult:
    text = raw_markdown or ""
    return ExtractionResult(
        source_path=source_path,
        extractor=extractor,
        status=status,
        raw_markdown=text,
        word_count=len(text.split()) if text else 0,
        char_count=len(text),
        warnings=list(warnings or []),
        metadata=dict(metadata or {}),
    )
