"""Stage 7: Self-learning integration — routing decisions → training pairs.

Tests:
  Step A  RouteLearnStore basics — save, count, read, tmp isolation
  Step B  record_confirmed — messages-format pair written correctly
  Step C  record_low_confidence — pending event written correctly
  Step D  add_correction — correction pair saved, confidence=1.0
  Step E  dispatch integration — high-confidence routes auto-saved
  Step F  dispatch integration — low-confidence "ask" saved as pending
  Step G  keyword fast-path saved with source=keyword, confidence=1.0
  Step H  Training pair format matches FT JSONL schema (messages array)
  Step I  Learner=None (default) — no file written, no regression
  Step J  Concurrent writes — multiple dispatch calls write distinct pairs

No real Ollama, NIM, or DocAgent connections.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

OPS = Path(__file__).resolve().parents[1]
WORKSPACE = OPS.parent
for _p in (str(OPS), str(WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _store(tmp_path):
    from core.route_learn import RouteLearnStore
    return RouteLearnStore(data_dir=tmp_path)


# ── Step A: RouteLearnStore basics ────────────────────────────────────────────

class TestRouteLearnStoreBasics:
    def test_empty_store_counts_zero(self, tmp_path):
        s = _store(tmp_path)
        assert s.confirmed_count() == 0
        assert s.pending_count() == 0

    def test_confirmed_count_after_record(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("make a report", "a.pdf", "docx", 0.92)
        assert s.confirmed_count() == 1

    def test_pending_count_after_record(self, tmp_path):
        s = _store(tmp_path)
        s.record_low_confidence("hmm", "none", 0.3)
        assert s.pending_count() == 1

    def test_read_confirmed_empty(self, tmp_path):
        s = _store(tmp_path)
        assert s.read_confirmed() == []

    def test_read_pending_empty(self, tmp_path):
        s = _store(tmp_path)
        assert s.read_pending() == []

    def test_multiple_records_append(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("report 1", "a.pdf", "docx", 0.9)
        s.record_confirmed("analyze 2", "b.pdf", "chat", 0.8)
        assert s.confirmed_count() == 2

    def test_confirmed_and_pending_independent(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("report", "x.pdf", "docx", 0.9)
        s.record_low_confidence("hmm", "", 0.2)
        assert s.confirmed_count() == 1
        assert s.pending_count() == 1


# ── Step B: record_confirmed format ──────────────────────────────────────────

class TestRecordConfirmed:
    def test_messages_array_has_three_roles(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("generate safety report", "data.pdf", "docx", 0.93)
        pair = s.read_confirmed()[0]
        msgs = pair["messages"]
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"

    def test_assistant_message_is_valid_json(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("analyze this", "b.pdf", "chat", 0.85)
        pair = s.read_confirmed()[0]
        assistant_content = pair["messages"][2]["content"]
        obj = json.loads(assistant_content)
        assert obj["intent"] == "chat"
        assert "confidence" in obj

    def test_intent_field_at_top_level(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("report on risks", "r.pdf", "docx", 0.91)
        pair = s.read_confirmed()[0]
        assert pair["intent"] == "docx"
        assert pair["confidence"] == pytest.approx(0.91, abs=0.001)

    def test_source_field_present(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("x", "", "chat", 0.8)
        pair = s.read_confirmed()[0]
        assert "route_learn" in pair["source"]

    def test_user_message_contains_prompt(self, tmp_path):
        s = _store(tmp_path)
        prompt = "generate a compliance procedure"
        s.record_confirmed(prompt, "docs.pdf", "docx", 0.95)
        pair = s.read_confirmed()[0]
        assert prompt in pair["messages"][1]["content"]

    def test_user_message_contains_file_names(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("analyze", "report.pdf, data.xlsx", "chat", 0.88)
        pair = s.read_confirmed()[0]
        assert "report.pdf" in pair["messages"][1]["content"]


# ── Step C: record_low_confidence format ──────────────────────────────────────

class TestRecordLowConfidence:
    def test_pending_event_has_prompt(self, tmp_path):
        s = _store(tmp_path)
        s.record_low_confidence("what should I do?", "none", 0.25)
        event = s.read_pending()[0]
        assert event["prompt"] == "what should I do?"

    def test_pending_event_has_confidence(self, tmp_path):
        s = _store(tmp_path)
        s.record_low_confidence("hm", "", 0.41)
        event = s.read_pending()[0]
        assert event["confidence"] == pytest.approx(0.41, abs=0.001)

    def test_pending_event_has_recorded_at(self, tmp_path):
        s = _store(tmp_path)
        s.record_low_confidence("x", "", 0.1)
        event = s.read_pending()[0]
        assert "recorded_at" in event

    def test_low_confidence_does_not_write_confirmed(self, tmp_path):
        s = _store(tmp_path)
        s.record_low_confidence("x", "", 0.1)
        assert s.confirmed_count() == 0


# ── Step D: add_correction ────────────────────────────────────────────────────

class TestAddCorrection:
    def test_correction_saved_to_confirmed(self, tmp_path):
        s = _store(tmp_path)
        s.add_correction("generate a report please", "a.pdf", "docx")
        assert s.confirmed_count() == 1

    def test_correction_confidence_is_1(self, tmp_path):
        s = _store(tmp_path)
        s.add_correction("analyze this spreadsheet", "x.xlsx", "chat")
        pair = s.read_confirmed()[0]
        obj = json.loads(pair["messages"][2]["content"])
        assert obj["confidence"] == 1.0

    def test_correction_source_is_correction(self, tmp_path):
        s = _store(tmp_path)
        s.add_correction("do something", "f.pdf", "chat")
        pair = s.read_confirmed()[0]
        assert pair["source"] == "route_learn/correction"

    def test_correction_intent_in_assistant(self, tmp_path):
        s = _store(tmp_path)
        s.add_correction("create a word file", "x.pdf", "docx")
        pair = s.read_confirmed()[0]
        obj = json.loads(pair["messages"][2]["content"])
        assert obj["intent"] == "docx"


# ── Step E: dispatch integration — high confidence ───────────────────────────

class TestDispatchHighConfidence:
    def test_high_confidence_route_saved(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.95)):
            dispatch("analyze risks in this doc", [], _learner=s)

        assert s.confirmed_count() == 1

    def test_confirmed_pair_has_correct_intent(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.88)):
            dispatch("explain this report", [{"name": "doc.pdf"}], _learner=s)

        pair = s.read_confirmed()[0]
        assert pair["intent"] == "chat"

    def test_no_pending_on_high_confidence(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("docx", 0.9)):
            dispatch("generate report", [], _learner=s)

        assert s.pending_count() == 0


# ── Step F: dispatch integration — low confidence ────────────────────────────

class TestDispatchLowConfidence:
    def test_low_confidence_saved_as_pending(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.3)):
            result = dispatch("hmm something", [], _learner=s)

        assert result["agent"] == "clarify"
        assert s.pending_count() == 1

    def test_low_confidence_not_saved_as_confirmed(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("ask", 0.1)):
            dispatch("?", [], _learner=s)

        assert s.confirmed_count() == 0

    def test_pending_event_confidence_matches(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.45)):
            dispatch("unclear request", [], _learner=s)

        event = s.read_pending()[0]
        assert event["confidence"] == pytest.approx(0.45, abs=0.01)


# ── Step G: keyword fast-path ─────────────────────────────────────────────────

class TestKeywordFastPath:
    def test_keyword_route_saved_with_confidence_1(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            dispatch("generate a safety report", [], _learner=s)

        assert s.confirmed_count() == 1
        pair = s.read_confirmed()[0]
        assert pair["confidence"] == 1.0

    def test_keyword_source_is_keyword(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            dispatch("generate procedure document", [], _learner=s)

        pair = s.read_confirmed()[0]
        assert "keyword" in pair["source"]

    def test_keyword_no_pending_event(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)

        with patch("router.fallback_router._keyword_fast_path", return_value="edit"):
            dispatch("update the spreadsheet", [{"name": "data.xlsx"}], _learner=s)

        assert s.pending_count() == 0


# ── Step H: FT JSONL schema validation ────────────────────────────────────────

class TestFTSchema:
    def test_confirmed_pair_is_valid_jsonl_line(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("make report", "a.pdf", "docx", 0.9)
        line = s.confirmed_path.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert isinstance(obj, dict)

    def test_messages_roles_in_correct_order(self, tmp_path):
        s = _store(tmp_path)
        s.record_confirmed("make report", "a.pdf", "docx", 0.9)
        pair = s.read_confirmed()[0]
        roles = [m["role"] for m in pair["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_assistant_content_parseable_intent(self, tmp_path):
        s = _store(tmp_path)
        for intent in ("docx", "chat", "ask", "edit"):
            s.record_confirmed(f"prompt for {intent}", "", intent, 0.8)

        for pair in s.read_confirmed():
            obj = json.loads(pair["messages"][2]["content"])
            assert obj["intent"] in ("docx", "chat", "ask", "edit")
            assert 0.0 <= obj["confidence"] <= 1.0

    def test_correction_pair_schema_valid(self, tmp_path):
        s = _store(tmp_path)
        s.add_correction("build a compliance report", "r.pdf", "docx")
        pair = s.read_confirmed()[0]
        assert len(pair["messages"]) == 3
        obj = json.loads(pair["messages"][2]["content"])
        assert obj["intent"] == "docx"
        assert obj["confidence"] == 1.0


# ── Step I: learner=None does not break anything ──────────────────────────────

class TestLearnerNoneNoRegression:
    def test_dispatch_without_learner_no_file_created(self, tmp_path):
        from sync_pipeline import dispatch
        before = list(tmp_path.iterdir())

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            dispatch("analyze this", [], _learner=None)

        after = list(tmp_path.iterdir())
        assert before == after

    def test_stages_1_to_6_tests_still_pass_without_learner(self, tmp_path):
        from sync_pipeline import dispatch
        with patch("router.fallback_router._keyword_fast_path", return_value="docx"):
            result = dispatch("generate report", [])
        assert "intent" in result


# ── Step J: concurrent writes ─────────────────────────────────────────────────

class TestConcurrentWrites:
    def test_concurrent_dispatch_writes_all_pairs(self, tmp_path):
        from sync_pipeline import dispatch
        s = _store(tmp_path)
        errors = []

        def worker(i):
            try:
                with patch("router.fallback_router._keyword_fast_path", return_value=None), \
                     patch("router.local_router.classify_file_intent",
                           return_value=("chat", 0.8 + i * 0.001)):
                    dispatch(f"prompt {i}", [], _learner=s)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert s.confirmed_count() == 10
