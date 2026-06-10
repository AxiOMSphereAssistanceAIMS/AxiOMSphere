"""
DOCSREG master registration record — formal JSON registration for the AIMS registry.

Produces a fully-formed, round-trip-stable registration record for every document
that completes the DOCSREG certification pipeline.  The record captures identity
fields, quality score, individual gate verdicts, certification status, timestamps,
and the path to the evidence directory.

The module is intentionally free of LLM calls, HTTP calls, and subprocess calls.
It uses only the Python standard library.

Exports
-------
RegistrationRecord : dataclass
    Immutable snapshot of a document's registration state.
RegistrationRecordBuilder : class
    Accumulates fields and constructs a :class:`RegistrationRecord` via
    :meth:`RegistrationRecordBuilder.build`.
create_builder() -> RegistrationRecordBuilder
    Module-level convenience factory — returns a fresh builder.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("docsreg_master_registration")

# ── Certification thresholds ───────────────────────────────────────────────────

_SCORE_CERTIFIED: float = 0.95
_SCORE_REJECTED: float = 0.60

_STATUS_CERTIFIED = "CERTIFIED"
_STATUS_REJECTED = "REJECTED"
_STATUS_PENDING = "PENDING"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class RegistrationRecord:
    """Immutable formal registration record for an AIMS document.

    Fields
    ------
    document_id : str
        Unique document identifier, e.g. ``"DOC-2026-001"``.
    document_title : str
        Human-readable document title.
    document_type : str
        Document category, e.g. ``"AIM"``, ``"PFM"``, ``"Preservation"``.
    document_version : str
        Version string, e.g. ``"1.0"``.
    certification_status : str
        One of ``"CERTIFIED"``, ``"REJECTED"``, or ``"PENDING"``.
    quality_score : float
        Aggregate quality score in the range ``[0.0, 1.0]``.
    gate_verdicts : dict[str, bool]
        Mapping of gate name → passed (True/False).
    created_at : str
        ISO-8601 UTC timestamp at which the record was created.
    certified_at : str
        ISO-8601 UTC timestamp at which the document was certified, or ``""``
        if not yet certified.
    evidence_dir : str
        Path to the evidence directory for this certification run.
    notes : str
        Optional free-text notes.  Defaults to ``""``.
    """

    document_id: str
    document_title: str
    document_type: str
    document_version: str
    certification_status: str
    quality_score: float
    gate_verdicts: dict
    created_at: str
    certified_at: str
    evidence_dir: str
    notes: str = ""

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of this record.

        The returned dict has a flat structure matching the dataclass fields.
        """
        return asdict(self)

    def to_json(self) -> str:
        """Return the record as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "RegistrationRecord":
        """Reconstruct a :class:`RegistrationRecord` from a dict.

        Args:
            data: A dict as produced by :meth:`to_dict`.

        Returns:
            A new :class:`RegistrationRecord` matching *data* exactly.
        """
        return cls(
            document_id=data["document_id"],
            document_title=data["document_title"],
            document_type=data["document_type"],
            document_version=data["document_version"],
            certification_status=data["certification_status"],
            quality_score=data["quality_score"],
            gate_verdicts=dict(data.get("gate_verdicts", {})),
            created_at=data["created_at"],
            certified_at=data.get("certified_at", ""),
            evidence_dir=data.get("evidence_dir", ""),
            notes=data.get("notes", ""),
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RegistrationRecord("
            f"document_id={self.document_id!r}, "
            f"certification_status={self.certification_status!r}, "
            f"quality_score={self.quality_score:.3f})"
        )


# ── Builder ────────────────────────────────────────────────────────────────────


class RegistrationRecordBuilder:
    """Accumulates fields and constructs a :class:`RegistrationRecord`.

    Usage
    -----
    >>> record = (
    ...     create_builder()
    ...     .set_document("DOC-2026-001", "Pump Failure Mode Analysis", "AIM", "1.0")
    ...     .set_quality_score(0.97)
    ...     .set_gate_verdict("evidence_gate", True)
    ...     .set_gate_verdict("precheck_gate", True)
    ...     .set_evidence_dir("/aims_workspace/evidence/DOC-2026-001")
    ...     .build()
    ... )
    """

    def __init__(self) -> None:
        self._document_id: str = ""
        self._document_title: str = ""
        self._document_type: str = ""
        self._document_version: str = ""
        self._quality_score: float = 0.0
        self._gate_verdicts: dict[str, bool] = {}
        self._evidence_dir: str = ""
        self._notes: str = ""
        self._created_at: str = ""

    # ── Setters (all return self for fluent chaining) ──────────────────────────

    def set_document(
        self,
        document_id: str,
        document_title: str,
        document_type: str,
        document_version: str,
    ) -> "RegistrationRecordBuilder":
        """Set the document identity fields.

        Args:
            document_id: Unique document identifier.
            document_title: Human-readable title.
            document_type: Document category (e.g. ``"AIM"``).
            document_version: Version string (e.g. ``"1.0"``).

        Returns:
            ``self`` for fluent chaining.
        """
        self._document_id = document_id
        self._document_title = document_title
        self._document_type = document_type
        self._document_version = document_version
        return self

    def set_quality_score(self, score: float) -> "RegistrationRecordBuilder":
        """Set the aggregate quality score.

        Args:
            score: A float in the range ``[0.0, 1.0]``.

        Returns:
            ``self`` for fluent chaining.
        """
        self._quality_score = score
        return self

    def set_gate_verdict(
        self, gate_name: str, passed: bool
    ) -> "RegistrationRecordBuilder":
        """Record the verdict for a single certification gate.

        Args:
            gate_name: Identifier of the gate, e.g. ``"evidence_gate"``.
            passed: ``True`` if the gate passed, ``False`` otherwise.

        Returns:
            ``self`` for fluent chaining.
        """
        self._gate_verdicts[gate_name] = passed
        return self

    def set_evidence_dir(self, evidence_dir: str) -> "RegistrationRecordBuilder":
        """Set the path to the evidence directory.

        Args:
            evidence_dir: Filesystem path to the evidence artefacts.

        Returns:
            ``self`` for fluent chaining.
        """
        self._evidence_dir = evidence_dir
        return self

    def set_notes(self, notes: str) -> "RegistrationRecordBuilder":
        """Set optional free-text notes.

        Args:
            notes: Free-text rationale or observations.

        Returns:
            ``self`` for fluent chaining.
        """
        self._notes = notes
        return self

    # ── Build ──────────────────────────────────────────────────────────────────

    def build(self) -> RegistrationRecord:
        """Construct and return a :class:`RegistrationRecord`.

        Validation
        ----------
        Raises :class:`ValueError` if ``document_id`` or ``document_title``
        is empty.

        Certification logic
        -------------------
        * ``"CERTIFIED"`` — ``quality_score >= 0.95`` **and** all
          ``gate_verdicts`` values are ``True`` (or no gates are present).
        * ``"REJECTED"`` — ``quality_score < 0.60``.
        * ``"PENDING"`` — everything else.

        Timestamps
        ----------
        ``created_at`` is set to the current UTC ISO-8601 timestamp if not
        already set.  ``certified_at`` is set to the current UTC ISO-8601
        timestamp when ``certification_status == "CERTIFIED"``; otherwise it
        is set to ``""``.

        Returns:
            A fully-populated :class:`RegistrationRecord`.

        Raises:
            ValueError: If ``document_id`` or ``document_title`` is empty.
        """
        if not self._document_id:
            raise ValueError("document_id must not be empty")
        if not self._document_title:
            raise ValueError("document_title must not be empty")

        now = datetime.now(tz=timezone.utc).isoformat()
        created_at = self._created_at or now

        # Determine certification status
        all_gates_pass = all(self._gate_verdicts.values()) if self._gate_verdicts else True
        if self._quality_score >= _SCORE_CERTIFIED and all_gates_pass:
            certification_status = _STATUS_CERTIFIED
        elif self._quality_score < _SCORE_REJECTED:
            certification_status = _STATUS_REJECTED
        else:
            certification_status = _STATUS_PENDING

        certified_at = now if certification_status == _STATUS_CERTIFIED else ""

        log.debug(
            "master_registration: build document_id=%r status=%r score=%.3f gates=%d",
            self._document_id,
            certification_status,
            self._quality_score,
            len(self._gate_verdicts),
        )

        return RegistrationRecord(
            document_id=self._document_id,
            document_title=self._document_title,
            document_type=self._document_type,
            document_version=self._document_version,
            certification_status=certification_status,
            quality_score=self._quality_score,
            gate_verdicts=dict(self._gate_verdicts),
            created_at=created_at,
            certified_at=certified_at,
            evidence_dir=self._evidence_dir,
            notes=self._notes,
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RegistrationRecordBuilder("
            f"document_id={self._document_id!r}, "
            f"quality_score={self._quality_score:.3f}, "
            f"gates={len(self._gate_verdicts)})"
        )


# ── Module-level convenience ───────────────────────────────────────────────────


def create_builder() -> RegistrationRecordBuilder:
    """Return a fresh :class:`RegistrationRecordBuilder`."""
    return RegistrationRecordBuilder()
