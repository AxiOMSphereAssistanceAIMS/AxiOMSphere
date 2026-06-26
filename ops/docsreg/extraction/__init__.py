"""DOCSREG extraction backends."""

from .extraction_models import ExtractionResult
from .markitdown_adapter import (
    MARKITDOWN_SUPPORTED_SUFFIXES,
    extract_with_markitdown,
    write_extraction_artifacts,
)

__all__ = [
    "ExtractionResult",
    "MARKITDOWN_SUPPORTED_SUFFIXES",
    "extract_with_markitdown",
    "write_extraction_artifacts",
]
