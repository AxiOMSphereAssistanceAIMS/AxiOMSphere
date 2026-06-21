"""Data models for DOCSREG archive extraction pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class ArchiveStatus(str, Enum):
    queued_for_extraction = "queued_for_extraction"
    extracted = "extracted"
    rejected_archive_safety_limit = "rejected_archive_safety_limit"
    unsupported_archive_extractor = "unsupported_archive_extractor"
    corrupt_archive = "corrupt_archive"


class MemberStatus(str, Enum):
    queued = "queued"
    unsupported_format = "unsupported_format"
    skipped_nested_archive_depth_limit = "skipped_nested_archive_depth_limit"


@dataclass
class ArchiveRecord:
    """High-level record for a discovered archive file."""

    path: Path
    extension: str
    sha256: str
    status: ArchiveStatus
    error: Optional[str] = None


@dataclass
class ExtractionResult:
    """Result of extracting one archive file."""

    archive_path: Path
    archive_sha256: str
    status: ArchiveStatus
    files_found: int = 0
    processable_found: int = 0
    unsupported_found: int = 0
    extracted_size_bytes: int = 0
    error: Optional[str] = None


@dataclass
class ExtractedFileRecord:
    """A single file extracted from an archive."""

    path: Path
    archive_path: Path
    member_path: str
    extension: str
    extracted_sha256: str
    nested_depth: int
    status: MemberStatus
    source_kind: str = "archive_member"
    archive_chain: List[str] = field(default_factory=list)
