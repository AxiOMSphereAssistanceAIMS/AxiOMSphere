"""
DOCSREG patch ledger — audit trail for every patch applied during certification.

Records every patch (stub fill, reference repair, format fix, etc.) applied
to a document during the certification cycle so that the full change history
is serialisable, queryable, and round-trip-stable.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It uses only the Python standard library.

Exports
-------
PatchEntry : dataclass
    Immutable record of a single patch event.
PatchLedger : class
    Ordered collection of PatchEntry records with query helpers and
    JSON serialisation support.
create_ledger() -> PatchLedger
    Module-level convenience factory — returns a fresh empty ledger.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("docsreg_patch_ledger")


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class PatchEntry:
    """Immutable record of a single patch applied to a document section.

    Fields
    ------
    patch_id : str
        Unique identifier, e.g. ``"patch-001"``.
    patch_type : str
        Category of the patch, e.g. ``"stub_fill"``, ``"reference_repair"``,
        ``"format_fix"``.
    section : str
        Heading of the document section that was patched.
    before : str
        Content of the section *before* the patch was applied.
    after : str
        Content of the section *after* the patch was applied.
    timestamp : str
        ISO-8601 UTC timestamp at which the patch was recorded.
    applied_by : str
        Identity of the component that applied the patch, e.g.
        ``"section_editor"``, ``"reference_governance"``, ``"manual"``.
    notes : str
        Optional free-text rationale.  Defaults to ``""``.
    """

    patch_id: str
    patch_type: str
    section: str
    before: str
    after: str
    timestamp: str
    applied_by: str
    notes: str = ""


# ── PatchLedger ────────────────────────────────────────────────────────────────


class PatchLedger:
    """Ordered audit trail of patches applied during a certification cycle.

    Usage
    -----
    >>> ledger = PatchLedger()
    >>> entry = ledger.record(
    ...     patch_type="stub_fill",
    ...     section="3.2 Scope",
    ...     before="[STUB]",
    ...     after="This procedure applies to all rotating equipment.",
    ...     applied_by="section_editor",
    ... )
    >>> ledger.to_json()
    '...'
    """

    def __init__(self) -> None:
        self._entries: list[PatchEntry] = []

    # ── Mutation ───────────────────────────────────────────────────────────────

    def record(
        self,
        patch_type: str,
        section: str,
        before: str,
        after: str,
        applied_by: str,
        notes: str = "",
    ) -> PatchEntry:
        """Record a new patch and append it to the ledger.

        Args:
            patch_type: Category of the patch (e.g. ``"stub_fill"``).
            section: Heading of the section that was patched.
            before: Content before the patch.
            after: Content after the patch.
            applied_by: Component or actor that applied the patch.
            notes: Optional free-text rationale.

        Returns:
            The :class:`PatchEntry` that was created and stored.
        """
        patch_id = f"patch-{len(self._entries) + 1:03d}"
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        entry = PatchEntry(
            patch_id=patch_id,
            patch_type=patch_type,
            section=section,
            before=before,
            after=after,
            timestamp=timestamp,
            applied_by=applied_by,
            notes=notes,
        )
        self._entries.append(entry)
        log.debug(
            "patch_ledger: recorded %s type=%r section=%r applied_by=%r",
            patch_id,
            patch_type,
            section,
            applied_by,
        )
        return entry

    # ── Queries ────────────────────────────────────────────────────────────────

    def entries(self) -> list[PatchEntry]:
        """Return all entries in insertion order."""
        return list(self._entries)

    def entries_for_section(self, section: str) -> list[PatchEntry]:
        """Return all entries whose *section* matches *section* exactly."""
        return [e for e in self._entries if e.section == section]

    def entries_by_type(self, patch_type: str) -> list[PatchEntry]:
        """Return all entries whose *patch_type* matches *patch_type* exactly."""
        return [e for e in self._entries if e.patch_type == patch_type]

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable summary of the ledger.

        The returned dict has the shape::

            {
                "entries": [<each PatchEntry as a dict>],
                "total": <int>
            }
        """
        return {
            "entries": [asdict(e) for e in self._entries],
            "total": len(self._entries),
        }

    def to_json(self) -> str:
        """Return the ledger as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "PatchLedger":
        """Rebuild a :class:`PatchLedger` from a dict produced by :meth:`to_dict`.

        Args:
            data: A dict with an ``"entries"`` key containing a list of
                PatchEntry dicts (as produced by :meth:`to_dict`).

        Returns:
            A new :class:`PatchLedger` whose entries match *data* exactly.
        """
        ledger = cls()
        for entry_dict in data.get("entries", []):
            entry = PatchEntry(
                patch_id=entry_dict["patch_id"],
                patch_type=entry_dict["patch_type"],
                section=entry_dict["section"],
                before=entry_dict["before"],
                after=entry_dict["after"],
                timestamp=entry_dict["timestamp"],
                applied_by=entry_dict["applied_by"],
                notes=entry_dict.get("notes", ""),
            )
            ledger._entries.append(entry)
        log.debug(
            "patch_ledger: from_dict loaded %d entries", len(ledger._entries)
        )
        return ledger

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:  # pragma: no cover
        return f"PatchLedger(entries={len(self._entries)})"


# ── Module-level convenience ───────────────────────────────────────────────────


def create_ledger() -> PatchLedger:
    """Return a fresh empty :class:`PatchLedger`."""
    return PatchLedger()
