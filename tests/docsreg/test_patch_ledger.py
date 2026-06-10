"""
Tests for ops.docsreg.docsreg_patch_ledger.

Coverage
--------
1. TestPatchEntry          — dataclass fields, default notes, field values
2. TestPatchLedgerRecord   — auto-generated patch_id and timestamp, returned
                             entry matches stored entry, notes default empty
3. TestPatchLedgerQueries  — entries(), entries_for_section(),
                             entries_by_type(), empty results on no match
4. TestPatchLedgerSerialization — to_dict() shape, total count, from_dict()
                                  round-trip, to_json() valid JSON, full
                                  round-trip fidelity
5. TestCreateLedger        — factory returns PatchLedger, starts empty
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ops.docsreg.docsreg_patch_ledger import (
    PatchEntry,
    PatchLedger,
    create_ledger,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_ledger_with_entries() -> PatchLedger:
    """Return a ledger pre-populated with three diverse entries."""
    ledger = PatchLedger()
    ledger.record(
        patch_type="stub_fill",
        section="1.0 Purpose",
        before="[STUB]",
        after="This procedure defines the inspection protocol.",
        applied_by="section_editor",
        notes="Filled missing purpose section.",
    )
    ledger.record(
        patch_type="reference_repair",
        section="2.0 References",
        before="See ISO XXXX.",
        after="See ISO 55001:2014.",
        applied_by="reference_governance",
    )
    ledger.record(
        patch_type="format_fix",
        section="1.0 Purpose",
        before="this procedure defines the inspection protocol.",
        after="This procedure defines the inspection protocol.",
        applied_by="manual",
        notes="Capitalised first letter.",
    )
    return ledger


# ── 1. PatchEntry dataclass ────────────────────────────────────────────────────


class TestPatchEntry:
    def test_all_fields_stored(self) -> None:
        entry = PatchEntry(
            patch_id="patch-001",
            patch_type="stub_fill",
            section="1.0 Purpose",
            before="[STUB]",
            after="Filled content.",
            timestamp="2026-06-10T00:00:00+00:00",
            applied_by="section_editor",
            notes="Some note.",
        )
        assert entry.patch_id == "patch-001"
        assert entry.patch_type == "stub_fill"
        assert entry.section == "1.0 Purpose"
        assert entry.before == "[STUB]"
        assert entry.after == "Filled content."
        assert entry.timestamp == "2026-06-10T00:00:00+00:00"
        assert entry.applied_by == "section_editor"
        assert entry.notes == "Some note."

    def test_notes_default_is_empty_string(self) -> None:
        entry = PatchEntry(
            patch_id="patch-001",
            patch_type="format_fix",
            section="2.0 Scope",
            before="old",
            after="new",
            timestamp="2026-06-10T00:00:00+00:00",
            applied_by="manual",
        )
        assert entry.notes == ""

    def test_patch_entry_is_dataclass(self) -> None:
        """PatchEntry instances must support equality by field values."""
        e1 = PatchEntry("p-1", "t", "s", "b", "a", "ts", "me", "n")
        e2 = PatchEntry("p-1", "t", "s", "b", "a", "ts", "me", "n")
        assert e1 == e2

    def test_patch_entry_fields_are_strings(self) -> None:
        entry = PatchEntry(
            patch_id="patch-999",
            patch_type="reference_repair",
            section="§ 5",
            before="old ref",
            after="new ref",
            timestamp="2026-01-01T12:00:00+00:00",
            applied_by="reference_governance",
        )
        for attr in ("patch_id", "patch_type", "section", "before",
                     "after", "timestamp", "applied_by", "notes"):
            assert isinstance(getattr(entry, attr), str), attr


# ── 2. PatchLedger.record() ────────────────────────────────────────────────────


class TestPatchLedgerRecord:
    def test_record_returns_patch_entry(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record("stub_fill", "1.0", "before", "after", "editor")
        assert isinstance(entry, PatchEntry)

    def test_first_patch_id_is_patch_001(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record("stub_fill", "1.0", "b", "a", "editor")
        assert entry.patch_id == "patch-001"

    def test_second_patch_id_is_patch_002(self) -> None:
        ledger = PatchLedger()
        ledger.record("stub_fill", "1.0", "b", "a", "editor")
        entry = ledger.record("format_fix", "2.0", "b", "a", "editor")
        assert entry.patch_id == "patch-002"

    def test_patch_ids_sequential(self) -> None:
        ledger = PatchLedger()
        ids = []
        for i in range(5):
            e = ledger.record("t", f"sec-{i}", "b", "a", "ed")
            ids.append(e.patch_id)
        assert ids == ["patch-001", "patch-002", "patch-003", "patch-004", "patch-005"]

    def test_timestamp_is_iso8601(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record("t", "s", "b", "a", "ed")
        # Must parse without raising
        parsed = datetime.fromisoformat(entry.timestamp)
        assert parsed.tzinfo is not None  # timezone-aware

    def test_returned_entry_matches_stored_entry(self) -> None:
        ledger = PatchLedger()
        returned = ledger.record("stub_fill", "§1", "old", "new", "ed", "note")
        stored = ledger.entries()[0]
        assert returned is stored

    def test_notes_default_empty_when_not_provided(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record("format_fix", "§2", "x", "y", "manual")
        assert entry.notes == ""

    def test_notes_stored_when_provided(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record("format_fix", "§2", "x", "y", "manual", notes="rationale")
        assert entry.notes == "rationale"

    def test_fields_preserved_correctly(self) -> None:
        ledger = PatchLedger()
        entry = ledger.record(
            patch_type="reference_repair",
            section="4.0 References",
            before="ISO XXXX",
            after="ISO 55001",
            applied_by="reference_governance",
            notes="Fixed ref",
        )
        assert entry.patch_type == "reference_repair"
        assert entry.section == "4.0 References"
        assert entry.before == "ISO XXXX"
        assert entry.after == "ISO 55001"
        assert entry.applied_by == "reference_governance"
        assert entry.notes == "Fixed ref"


# ── 3. Query methods ───────────────────────────────────────────────────────────


class TestPatchLedgerQueries:
    def test_entries_returns_all_in_order(self) -> None:
        ledger = _make_ledger_with_entries()
        all_entries = ledger.entries()
        assert len(all_entries) == 3
        assert all_entries[0].patch_id == "patch-001"
        assert all_entries[1].patch_id == "patch-002"
        assert all_entries[2].patch_id == "patch-003"

    def test_entries_returns_copy_not_reference(self) -> None:
        """Mutating the returned list must not affect the ledger."""
        ledger = _make_ledger_with_entries()
        copy = ledger.entries()
        copy.clear()
        assert len(ledger.entries()) == 3

    def test_entries_for_section_filters_correctly(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_for_section("1.0 Purpose")
        assert len(result) == 2
        for e in result:
            assert e.section == "1.0 Purpose"

    def test_entries_for_section_single_match(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_for_section("2.0 References")
        assert len(result) == 1
        assert result[0].patch_type == "reference_repair"

    def test_entries_for_section_no_match_returns_empty(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_for_section("99.0 Nonexistent")
        assert result == []

    def test_entries_by_type_filters_correctly(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_by_type("stub_fill")
        assert len(result) == 1
        assert result[0].section == "1.0 Purpose"

    def test_entries_by_type_format_fix(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_by_type("format_fix")
        assert len(result) == 1
        assert result[0].applied_by == "manual"

    def test_entries_by_type_no_match_returns_empty(self) -> None:
        ledger = _make_ledger_with_entries()
        result = ledger.entries_by_type("unknown_type")
        assert result == []

    def test_empty_ledger_queries_return_empty(self) -> None:
        ledger = PatchLedger()
        assert ledger.entries() == []
        assert ledger.entries_for_section("§1") == []
        assert ledger.entries_by_type("stub_fill") == []

    def test_len_reflects_entry_count(self) -> None:
        ledger = PatchLedger()
        assert len(ledger) == 0
        ledger.record("t", "s", "b", "a", "ed")
        assert len(ledger) == 1
        ledger.record("t", "s2", "b", "a", "ed")
        assert len(ledger) == 2


# ── 4. Serialisation ───────────────────────────────────────────────────────────


class TestPatchLedgerSerialization:
    def test_to_dict_has_entries_key(self) -> None:
        ledger = _make_ledger_with_entries()
        d = ledger.to_dict()
        assert "entries" in d

    def test_to_dict_has_total_key(self) -> None:
        ledger = _make_ledger_with_entries()
        d = ledger.to_dict()
        assert "total" in d

    def test_to_dict_total_matches_entry_count(self) -> None:
        ledger = _make_ledger_with_entries()
        d = ledger.to_dict()
        assert d["total"] == 3
        assert len(d["entries"]) == 3

    def test_to_dict_empty_ledger(self) -> None:
        ledger = PatchLedger()
        d = ledger.to_dict()
        assert d["total"] == 0
        assert d["entries"] == []

    def test_to_json_is_valid_json(self) -> None:
        ledger = _make_ledger_with_entries()
        raw = ledger.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_to_json_contains_all_entries(self) -> None:
        ledger = _make_ledger_with_entries()
        parsed = json.loads(ledger.to_json())
        assert parsed["total"] == 3
        assert len(parsed["entries"]) == 3

    def test_from_dict_round_trip_entry_count(self) -> None:
        ledger = _make_ledger_with_entries()
        rebuilt = PatchLedger.from_dict(ledger.to_dict())
        assert len(rebuilt.entries()) == 3

    def test_from_dict_round_trip_field_fidelity(self) -> None:
        ledger = _make_ledger_with_entries()
        original_entries = ledger.entries()
        rebuilt = PatchLedger.from_dict(ledger.to_dict())
        rebuilt_entries = rebuilt.entries()
        for orig, reblt in zip(original_entries, rebuilt_entries):
            assert orig == reblt

    def test_from_dict_empty_data(self) -> None:
        rebuilt = PatchLedger.from_dict({"entries": [], "total": 0})
        assert len(rebuilt.entries()) == 0

    def test_from_dict_missing_entries_key(self) -> None:
        """from_dict should handle dicts without 'entries' gracefully."""
        rebuilt = PatchLedger.from_dict({})
        assert len(rebuilt.entries()) == 0

    def test_round_trip_via_json_string(self) -> None:
        """to_json → json.loads → from_dict must preserve all data."""
        ledger = _make_ledger_with_entries()
        json_str = ledger.to_json()
        data = json.loads(json_str)
        rebuilt = PatchLedger.from_dict(data)
        assert rebuilt.entries() == ledger.entries()

    def test_from_dict_preserves_notes(self) -> None:
        ledger = PatchLedger()
        ledger.record("stub_fill", "§1", "b", "a", "ed", notes="important note")
        rebuilt = PatchLedger.from_dict(ledger.to_dict())
        assert rebuilt.entries()[0].notes == "important note"

    def test_from_dict_default_notes_when_absent(self) -> None:
        """from_dict must default notes to '' if the key is missing."""
        data = {
            "entries": [
                {
                    "patch_id": "patch-001",
                    "patch_type": "format_fix",
                    "section": "§1",
                    "before": "b",
                    "after": "a",
                    "timestamp": "2026-06-10T00:00:00+00:00",
                    "applied_by": "manual",
                    # "notes" deliberately absent
                }
            ],
            "total": 1,
        }
        rebuilt = PatchLedger.from_dict(data)
        assert rebuilt.entries()[0].notes == ""


# ── 5. create_ledger() factory ─────────────────────────────────────────────────


class TestCreateLedger:
    def test_returns_patch_ledger_instance(self) -> None:
        ledger = create_ledger()
        assert isinstance(ledger, PatchLedger)

    def test_starts_empty(self) -> None:
        ledger = create_ledger()
        assert len(ledger) == 0
        assert ledger.entries() == []

    def test_each_call_returns_independent_instance(self) -> None:
        l1 = create_ledger()
        l2 = create_ledger()
        l1.record("t", "s", "b", "a", "ed")
        assert len(l1) == 1
        assert len(l2) == 0
