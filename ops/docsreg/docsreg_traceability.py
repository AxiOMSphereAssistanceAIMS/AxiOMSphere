"""
DOCSREG traceability map — per-section provenance tracking.

Maps each document section to its source document, generation cycle, and
full edit history so that every change made during the certification pipeline
is attributable and auditable.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It uses only the Python standard library.

Exports
-------
EditEvent : dataclass
    Immutable record of a single edit applied to a section.
SectionTrace : dataclass
    Provenance record for one document section: source, cycle, and history.
TraceabilityMap : class
    Ordered collection of SectionTrace records with query helpers and
    JSON serialisation support.
create_map() -> TraceabilityMap
    Module-level convenience factory — returns a fresh empty map.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("docsreg_traceability")


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class EditEvent:
    """Immutable record of a single edit applied to a document section.

    Fields
    ------
    editor : str
        Identity of the component that performed the edit, e.g.
        ``"section_editor"``, ``"reference_governance"``, ``"manual"``.
    action : str
        Short description of what was done, e.g. ``"initial_fill"``,
        ``"repair"``, ``"format_fix"``.
    timestamp : str
        ISO-8601 UTC timestamp at which the edit was recorded.
    notes : str
        Optional free-text rationale.  Defaults to ``""``.
    """

    editor: str
    action: str
    timestamp: str
    notes: str = ""


@dataclass
class SectionTrace:
    """Provenance record for a single document section.

    Fields
    ------
    section : str
        Section heading, e.g. ``"1.0 INTRODUCTION"``.
    source_document : str
        Name or path of the source document that seeded this section.
    generation_cycle : int
        Which generation cycle (1, 2, 3 …) produced this section.
    edit_history : list[EditEvent]
        Ordered list of edits applied to this section since registration.
        Defaults to an empty list (each instance gets its own list).
    """

    section: str
    source_document: str
    generation_cycle: int
    edit_history: list[EditEvent] = field(default_factory=list)


# ── TraceabilityMap ────────────────────────────────────────────────────────────


class TraceabilityMap:
    """Ordered collection of per-section provenance records.

    Usage
    -----
    >>> tmap = TraceabilityMap()
    >>> trace = tmap.register("1.0 INTRODUCTION", "source.docx", 1)
    >>> event = tmap.record_edit("1.0 INTRODUCTION", "section_editor", "initial_fill")
    >>> tmap.to_json()
    '...'
    """

    def __init__(self) -> None:
        # Preserve insertion order; Python 3.7+ dicts are ordered.
        self._traces: dict[str, SectionTrace] = {}

    # ── Mutation ───────────────────────────────────────────────────────────────

    def register(
        self,
        section: str,
        source_document: str,
        generation_cycle: int,
    ) -> SectionTrace:
        """Create a :class:`SectionTrace` and store it in the map.

        Args:
            section: Section heading (must be unique within this map).
            source_document: Name or path of the document that seeded the
                section.
            generation_cycle: Generation cycle number (1-based).

        Returns:
            The newly created :class:`SectionTrace`.

        Raises:
            ValueError: If *section* has already been registered.
        """
        if section in self._traces:
            raise ValueError(
                f"Section already registered: {section!r}. "
                "Use record_edit() to append further edits."
            )
        trace = SectionTrace(
            section=section,
            source_document=source_document,
            generation_cycle=generation_cycle,
        )
        self._traces[section] = trace
        log.debug(
            "traceability_map: registered section=%r source=%r cycle=%d",
            section,
            source_document,
            generation_cycle,
        )
        return trace

    def record_edit(
        self,
        section: str,
        editor: str,
        action: str,
        notes: str = "",
    ) -> EditEvent:
        """Append an :class:`EditEvent` to the named section's edit history.

        Args:
            section: Heading of the section to edit (must already be
                registered via :meth:`register`).
            editor: Component or actor performing the edit.
            action: Short description of the edit action.
            notes: Optional free-text rationale.

        Returns:
            The :class:`EditEvent` that was created and appended.

        Raises:
            KeyError: If *section* has not been registered.
        """
        if section not in self._traces:
            raise KeyError(
                f"Section not registered: {section!r}. "
                "Call register() before record_edit()."
            )
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        event = EditEvent(
            editor=editor,
            action=action,
            timestamp=timestamp,
            notes=notes,
        )
        self._traces[section].edit_history.append(event)
        log.debug(
            "traceability_map: edit section=%r editor=%r action=%r",
            section,
            editor,
            action,
        )
        return event

    # ── Queries ────────────────────────────────────────────────────────────────

    def get(self, section: str) -> SectionTrace:
        """Return the :class:`SectionTrace` for *section*.

        Raises:
            KeyError: If *section* has not been registered.
        """
        try:
            return self._traces[section]
        except KeyError:
            raise KeyError(f"Section not found in traceability map: {section!r}")

    def sections(self) -> list[str]:
        """Return all registered section headings in insertion order."""
        return list(self._traces.keys())

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of the map.

        The returned dict has the shape::

            {
                "sections": {
                    "<heading>": {
                        "section": str,
                        "source_document": str,
                        "generation_cycle": int,
                        "edit_history": [<EditEvent as dict>, ...]
                    },
                    ...
                },
                "total": <int>
            }
        """
        return {
            "sections": {
                heading: asdict(trace)
                for heading, trace in self._traces.items()
            },
            "total": len(self._traces),
        }

    def to_json(self) -> str:
        """Return the map as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "TraceabilityMap":
        """Rebuild a :class:`TraceabilityMap` from a dict produced by
        :meth:`to_dict`.

        Args:
            data: A dict with a ``"sections"`` key mapping headings to
                SectionTrace dicts (as produced by :meth:`to_dict`).

        Returns:
            A new :class:`TraceabilityMap` whose traces match *data* exactly.
        """
        tmap = cls()
        for heading, trace_dict in data.get("sections", {}).items():
            edit_history = [
                EditEvent(
                    editor=e["editor"],
                    action=e["action"],
                    timestamp=e["timestamp"],
                    notes=e.get("notes", ""),
                )
                for e in trace_dict.get("edit_history", [])
            ]
            trace = SectionTrace(
                section=trace_dict["section"],
                source_document=trace_dict["source_document"],
                generation_cycle=trace_dict["generation_cycle"],
                edit_history=edit_history,
            )
            tmap._traces[heading] = trace
        log.debug(
            "traceability_map: from_dict loaded %d sections", len(tmap._traces)
        )
        return tmap

    def __len__(self) -> int:
        return len(self._traces)

    def __repr__(self) -> str:  # pragma: no cover
        return f"TraceabilityMap(sections={len(self._traces)})"


# ── Module-level convenience ───────────────────────────────────────────────────


def create_map() -> TraceabilityMap:
    """Return a fresh empty :class:`TraceabilityMap`."""
    return TraceabilityMap()
