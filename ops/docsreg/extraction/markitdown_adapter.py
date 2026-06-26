from __future__ import annotations

"""Compatibility wrapper around the project-wide normalization adapter."""

import importlib
from importlib import metadata as importlib_metadata

from ops.document_normalization.markitdown_adapter import (  # noqa: F401
    MARKITDOWN_SUPPORTED_SUFFIXES,
    extract_with_markitdown,
    write_extraction_artifacts,
)
