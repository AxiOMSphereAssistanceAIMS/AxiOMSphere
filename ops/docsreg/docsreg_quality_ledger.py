"""
DOCSREG per-cycle quality ledger — tracks quality scores across fresh-start
cycles for a document type.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Union

log = logging.getLogger("docsreg_quality_ledger")

# ── Constants ──────────────────────────────────────────────────────────────────

QUALITY_LEDGER_FILE: str = "document_type_quality_ledger.json"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class QualityLedgerEntry:
    """Record of quality metrics for a single certification cycle."""

    cycle_id: str
    document_type: str
    quality: float
    section_coverage: float
    fresh_start_reproducibility: float   # from FreshStartEvidence.reproducibility_metric
    passed: bool
    timestamp_utc: str
    notes: str = ""


# ── QualityLedger ──────────────────────────────────────────────────────────────


class QualityLedger:
    """Ordered collection of :class:`QualityLedgerEntry` records.

    Provides quality-history access and JSON round-trip serialisation.
    All mutating and query operations are internally safe — the class does
    not raise; callers should use module-level :func:`write_quality_ledger` /
    :func:`read_quality_ledger` for I/O.
    """

    def __init__(self) -> None:
        self._entries: list[QualityLedgerEntry] = []

    # ── Mutation ───────────────────────────────────────────────────────────────

    def append(self, entry: QualityLedgerEntry) -> None:
        """Append *entry* to the ledger."""
        self._entries.append(entry)
        log.debug(
            "quality_ledger: appended cycle_id=%r quality=%.4f type=%r",
            entry.cycle_id,
            entry.quality,
            entry.document_type,
        )

    # ── Queries ────────────────────────────────────────────────────────────────

    def entries(self) -> list[QualityLedgerEntry]:
        """Return a copy of all entries in insertion order."""
        return list(self._entries)

    def quality_history(self) -> list:
        """Return ordered quality scores (oldest first)."""
        return [e.quality for e in self._entries]

    def best_quality(self) -> float:
        """Return the maximum quality score seen; ``0.0`` if ledger is empty."""
        if not self._entries:
            return 0.0
        return max(e.quality for e in self._entries)

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict.

        Shape::

            {
                "entries": [<each QualityLedgerEntry as dict via asdict()>],
                "total": <int>
            }
        """
        return {
            "entries": [asdict(e) for e in self._entries],
            "total": len(self._entries),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QualityLedger":
        """Rebuild a :class:`QualityLedger` from a dict produced by :meth:`to_dict`.

        Returns an empty ledger if *data* is malformed.  Never raises.
        """
        try:
            ledger = cls()
            for raw in data.get("entries", []):
                entry = QualityLedgerEntry(
                    cycle_id=raw["cycle_id"],
                    document_type=raw["document_type"],
                    quality=float(raw["quality"]),
                    section_coverage=float(raw["section_coverage"]),
                    fresh_start_reproducibility=float(
                        raw["fresh_start_reproducibility"]
                    ),
                    passed=bool(raw["passed"]),
                    timestamp_utc=raw["timestamp_utc"],
                    notes=raw.get("notes", ""),
                )
                ledger._entries.append(entry)
            log.debug("quality_ledger: from_dict loaded %d entries", len(ledger._entries))
            return ledger
        except Exception as exc:
            log.error("quality_ledger: from_dict failed: %s — returning empty ledger", exc)
            return cls()

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:  # pragma: no cover
        return f"QualityLedger(entries={len(self._entries)})"


# ── Module-level I/O functions ─────────────────────────────────────────────────


def write_quality_ledger(ledger: QualityLedger, cycle_dir: Union[str, Path]) -> bool:
    """Write *ledger* JSON to ``<cycle_dir>/evidence/document_type_quality_ledger.json``.

    Creates ``evidence/`` if absent.  Returns ``True`` on success, ``False`` on
    any error.  Never raises.
    """
    try:
        evidence_dir = Path(cycle_dir) / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        target = evidence_dir / QUALITY_LEDGER_FILE
        target.write_text(json.dumps(ledger.to_dict(), indent=2), encoding="utf-8")
        log.info("quality_ledger: wrote %d entries to %s", len(ledger), target)
        return True
    except Exception as exc:
        log.error("quality_ledger: write failed: %s", exc)
        return False


def read_quality_ledger(cycle_dir: Union[str, Path]) -> QualityLedger:
    """Read ledger from ``<cycle_dir>/evidence/document_type_quality_ledger.json``.

    Returns an empty :class:`QualityLedger` if the file is absent or malformed.
    Never raises.
    """
    try:
        target = Path(cycle_dir) / "evidence" / QUALITY_LEDGER_FILE
        if not target.exists():
            log.warning("quality_ledger: file not found at %s — returning empty ledger", target)
            return QualityLedger()
        data = json.loads(target.read_text(encoding="utf-8"))
        return QualityLedger.from_dict(data)
    except Exception as exc:
        log.error("quality_ledger: read failed: %s — returning empty ledger", exc)
        return QualityLedger()
