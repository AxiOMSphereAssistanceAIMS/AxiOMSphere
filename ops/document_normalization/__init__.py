"""Project-wide document normalization layer.

This package hosts the canonical source-normalization contract used by
DOCSREG, DOCGEN, and downstream consumers such as learning capture.
MarkItDown is an extraction backend only; it does not certify, author, or
render documents.
"""

from .markitdown_adapter import (
    MARKITDOWN_SUPPORTED_SUFFIXES,
    extract_with_markitdown,
    write_extraction_artifacts,
)
from .source_markdown_chunker import chunk_markdown

__all__ = [
    "MARKITDOWN_SUPPORTED_SUFFIXES",
    "extract_with_markitdown",
    "write_extraction_artifacts",
    "chunk_markdown",
]
