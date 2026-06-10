"""
Tests for ops/docsreg/docsreg_traceability.py — MASTER_TRACEABILITY_MAP gate.

Covers:
- EditEvent dataclass fields and defaults
- SectionTrace dataclass fields, default edit_history, and default_factory independence
- TraceabilityMap.register() — happy path, insertion-order sections(), ValueError on duplicate
- TraceabilityMap.record_edit() — appends EditEvent, timestamp format, KeyError on unregistered
- TraceabilityMap.get() — returns correct trace, KeyError on missing
- TraceabilityMap serialisation — to_dict() structure, from_dict() round-trip,
  to_json() valid JSON, edit_history preserved through round-trip
- create_map() — returns TraceabilityMap, starts empty
"""
from __future__ import annotations

import json

import pytest

from ops.docsreg.docsreg_traceability import (
    EditEvent,
    SectionTrace,
    TraceabilityMap,
    create_map,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

SECTION_A = "1.0 INTRODUCTION"
SECTION_B = "2.0 SCOPE"
SECTION_C = "3.1 DEFINITIONS"

SOURCE_DOC = "template_v2.docx"
CYCLE_1 = 1
CYCLE_2 = 2


# ── TestEditEvent ──────────────────────────────────────────────────────────────


class TestEditEvent:
    def test_fields_stored_correctly(self):
        event = EditEvent(
            editor="section_editor",
            action="initial_fill",
            timestamp="2026-06-10T08:00:00+00:00",
        )
        assert event.editor == "section_editor"
        assert event.action == "initial_fill"
        assert event.timestamp == "2026-06-10T08:00:00+00:00"

    def test_default_notes_is_empty_string(self):
        event = EditEvent(
            editor="reference_governance",
            action="repair",
            timestamp="2026-06-10T09:00:00+00:00",
        )
        assert event.notes == ""

    def test_explicit_notes_stored(self):
        event = EditEvent(
            editor="manual",
            action="format_fix",
            timestamp="2026-06-10T10:00:00+00:00",
            notes="Corrected heading capitalisation.",
        )
        assert event.notes == "Corrected heading capitalisation."

    def test_is_dataclass(self):
        # Verify it behaves as a dataclass (equality by value)
        e1 = EditEvent("ed", "act", "2026-01-01T00:00:00+00:00")
        e2 = EditEvent("ed", "act", "2026-01-01T00:00:00+00:00")
        assert e1 == e2


# ── TestSectionTrace ───────────────────────────────────────────────────────────


class TestSectionTrace:
    def test_fields_stored_correctly(self):
        trace = SectionTrace(
            section=SECTION_A,
            source_document=SOURCE_DOC,
            generation_cycle=CYCLE_1,
        )
        assert trace.section == SECTION_A
        assert trace.source_document == SOURCE_DOC
        assert trace.generation_cycle == CYCLE_1

    def test_default_edit_history_is_empty_list(self):
        trace = SectionTrace(
            section=SECTION_A,
            source_document=SOURCE_DOC,
            generation_cycle=CYCLE_1,
        )
        assert trace.edit_history == []

    def test_default_factory_independence(self):
        """Two SectionTrace instances must not share the same edit_history list."""
        t1 = SectionTrace(SECTION_A, SOURCE_DOC, CYCLE_1)
        t2 = SectionTrace(SECTION_B, SOURCE_DOC, CYCLE_1)
        t1.edit_history.append(
            EditEvent("editor", "action", "2026-06-10T00:00:00+00:00")
        )
        assert t2.edit_history == [], (
            "default_factory must create independent lists per instance"
        )

    def test_explicit_edit_history(self):
        event = EditEvent("ed", "act", "2026-06-10T00:00:00+00:00")
        trace = SectionTrace(
            section=SECTION_A,
            source_document=SOURCE_DOC,
            generation_cycle=CYCLE_1,
            edit_history=[event],
        )
        assert len(trace.edit_history) == 1
        assert trace.edit_history[0] is event


# ── TestTraceabilityMapRegister ────────────────────────────────────────────────


class TestTraceabilityMapRegister:
    def test_register_returns_section_trace(self):
        tmap = TraceabilityMap()
        trace = tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        assert isinstance(trace, SectionTrace)

    def test_register_stores_correct_fields(self):
        tmap = TraceabilityMap()
        trace = tmap.register(SECTION_A, SOURCE_DOC, CYCLE_2)
        assert trace.section == SECTION_A
        assert trace.source_document == SOURCE_DOC
        assert trace.generation_cycle == CYCLE_2

    def test_register_new_trace_has_empty_edit_history(self):
        tmap = TraceabilityMap()
        trace = tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        assert trace.edit_history == []

    def test_sections_returns_insertion_order(self):
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        tmap.register(SECTION_B, SOURCE_DOC, CYCLE_1)
        tmap.register(SECTION_C, SOURCE_DOC, CYCLE_1)
        assert tmap.sections() == [SECTION_A, SECTION_B, SECTION_C]

    def test_sections_empty_on_new_map(self):
        tmap = TraceabilityMap()
        assert tmap.sections() == []

    def test_register_duplicate_raises_value_error(self):
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        with pytest.raises(ValueError, match=SECTION_A):
            tmap.register(SECTION_A, "other_source.docx", CYCLE_2)

    def test_len_reflects_registered_count(self):
        tmap = TraceabilityMap()
        assert len(tmap) == 0
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        assert len(tmap) == 1
        tmap.register(SECTION_B, SOURCE_DOC, CYCLE_1)
        assert len(tmap) == 2


# ── TestTraceabilityMapRecordEdit ──────────────────────────────────────────────


class TestTraceabilityMapRecordEdit:
    def _populated_map(self) -> TraceabilityMap:
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        return tmap

    def test_record_edit_returns_edit_event(self):
        tmap = self._populated_map()
        event = tmap.record_edit(SECTION_A, "section_editor", "initial_fill")
        assert isinstance(event, EditEvent)

    def test_record_edit_appends_to_history(self):
        tmap = self._populated_map()
        tmap.record_edit(SECTION_A, "section_editor", "initial_fill")
        tmap.record_edit(SECTION_A, "reference_governance", "repair")
        trace = tmap.get(SECTION_A)
        assert len(trace.edit_history) == 2

    def test_record_edit_stores_correct_fields(self):
        tmap = self._populated_map()
        event = tmap.record_edit(
            SECTION_A, "section_editor", "initial_fill", notes="first pass"
        )
        assert event.editor == "section_editor"
        assert event.action == "initial_fill"
        assert event.notes == "first pass"

    def test_record_edit_timestamp_is_iso8601(self):
        tmap = self._populated_map()
        event = tmap.record_edit(SECTION_A, "ed", "act")
        # Must be parseable as ISO-8601; fromisoformat raises if malformed
        from datetime import datetime
        parsed = datetime.fromisoformat(event.timestamp)
        assert parsed is not None

    def test_record_edit_default_notes_empty(self):
        tmap = self._populated_map()
        event = tmap.record_edit(SECTION_A, "ed", "act")
        assert event.notes == ""

    def test_record_edit_on_unregistered_raises_key_error(self):
        tmap = TraceabilityMap()
        with pytest.raises(KeyError, match=SECTION_A):
            tmap.record_edit(SECTION_A, "ed", "act")

    def test_multiple_sections_do_not_share_history(self):
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        tmap.register(SECTION_B, SOURCE_DOC, CYCLE_1)
        tmap.record_edit(SECTION_A, "ed", "act")
        assert len(tmap.get(SECTION_B).edit_history) == 0


# ── TestTraceabilityMapGet ─────────────────────────────────────────────────────


class TestTraceabilityMapGet:
    def test_get_returns_correct_trace(self):
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        tmap.register(SECTION_B, "other.docx", CYCLE_2)
        trace = tmap.get(SECTION_B)
        assert trace.section == SECTION_B
        assert trace.source_document == "other.docx"
        assert trace.generation_cycle == CYCLE_2

    def test_get_on_missing_section_raises_key_error(self):
        tmap = TraceabilityMap()
        with pytest.raises(KeyError, match=SECTION_A):
            tmap.get(SECTION_A)

    def test_get_returns_same_object_as_register(self):
        tmap = TraceabilityMap()
        registered = tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        retrieved = tmap.get(SECTION_A)
        assert registered is retrieved


# ── TestTraceabilityMapSerialization ───────────────────────────────────────────


class TestTraceabilityMapSerialization:
    def _full_map(self) -> TraceabilityMap:
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        tmap.record_edit(SECTION_A, "section_editor", "initial_fill", "first pass")
        tmap.record_edit(SECTION_A, "reference_governance", "repair")
        tmap.register(SECTION_B, "other.docx", CYCLE_2)
        return tmap

    def test_to_dict_top_level_keys(self):
        tmap = self._full_map()
        d = tmap.to_dict()
        assert "sections" in d
        assert "total" in d

    def test_to_dict_total_matches_registered_count(self):
        tmap = self._full_map()
        d = tmap.to_dict()
        assert d["total"] == 2

    def test_to_dict_sections_keys_match_headings(self):
        tmap = self._full_map()
        d = tmap.to_dict()
        assert set(d["sections"].keys()) == {SECTION_A, SECTION_B}

    def test_to_dict_section_fields_present(self):
        tmap = TraceabilityMap()
        tmap.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        d = tmap.to_dict()
        section_data = d["sections"][SECTION_A]
        assert "section" in section_data
        assert "source_document" in section_data
        assert "generation_cycle" in section_data
        assert "edit_history" in section_data

    def test_to_dict_edit_history_preserved(self):
        tmap = self._full_map()
        d = tmap.to_dict()
        history = d["sections"][SECTION_A]["edit_history"]
        assert len(history) == 2
        assert history[0]["editor"] == "section_editor"
        assert history[0]["action"] == "initial_fill"
        assert history[0]["notes"] == "first pass"
        assert history[1]["editor"] == "reference_governance"

    def test_to_json_returns_valid_json_string(self):
        tmap = self._full_map()
        raw = tmap.to_json()
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert "sections" in parsed

    def test_from_dict_round_trip_section_count(self):
        tmap = self._full_map()
        rebuilt = TraceabilityMap.from_dict(tmap.to_dict())
        assert len(rebuilt) == len(tmap)

    def test_from_dict_round_trip_section_fields(self):
        tmap = self._full_map()
        rebuilt = TraceabilityMap.from_dict(tmap.to_dict())
        trace = rebuilt.get(SECTION_A)
        assert trace.section == SECTION_A
        assert trace.source_document == SOURCE_DOC
        assert trace.generation_cycle == CYCLE_1

    def test_from_dict_round_trip_edit_history(self):
        tmap = self._full_map()
        rebuilt = TraceabilityMap.from_dict(tmap.to_dict())
        history = rebuilt.get(SECTION_A).edit_history
        assert len(history) == 2
        assert history[0].editor == "section_editor"
        assert history[0].action == "initial_fill"
        assert history[0].notes == "first pass"
        assert history[1].editor == "reference_governance"

    def test_from_dict_round_trip_insertion_order(self):
        tmap = self._full_map()
        rebuilt = TraceabilityMap.from_dict(tmap.to_dict())
        assert rebuilt.sections() == [SECTION_A, SECTION_B]

    def test_from_dict_empty_sections(self):
        rebuilt = TraceabilityMap.from_dict({"sections": {}, "total": 0})
        assert len(rebuilt) == 0
        assert rebuilt.sections() == []

    def test_from_dict_missing_sections_key(self):
        rebuilt = TraceabilityMap.from_dict({})
        assert len(rebuilt) == 0

    def test_to_json_edit_history_round_trip(self):
        tmap = self._full_map()
        raw = tmap.to_json()
        rebuilt = TraceabilityMap.from_dict(json.loads(raw))
        assert len(rebuilt.get(SECTION_A).edit_history) == 2


# ── TestCreateMap ──────────────────────────────────────────────────────────────


class TestCreateMap:
    def test_returns_traceability_map_instance(self):
        tmap = create_map()
        assert isinstance(tmap, TraceabilityMap)

    def test_starts_empty(self):
        tmap = create_map()
        assert len(tmap) == 0
        assert tmap.sections() == []

    def test_independent_maps(self):
        """create_map() must return a fresh instance each time."""
        m1 = create_map()
        m2 = create_map()
        m1.register(SECTION_A, SOURCE_DOC, CYCLE_1)
        assert len(m2) == 0, "create_map() must not share state between calls"
