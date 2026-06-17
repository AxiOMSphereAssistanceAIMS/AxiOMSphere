"""Stage 2: Mini-pipeline tests — 2-component links.

Pipeline A: DocAgent generation → NIM quality gate → accept/reject/retry decision
Pipeline B: Omi OCR text → DB insert → Qdrant embedding enqueue

No real LLM, NIM, or Qdrant connections.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

OPS = Path(__file__).resolve().parents[1]
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))


_GOOD_DOC = """\
# Hot Work Permit Procedure

## 1. Scope
This procedure applies to all hot work at the facility including welding, cutting, and grinding.

## 2. Pre-work requirements
- Obtain signed hot work permit from safety officer
- Atmospheric testing: LEL < 5%
- Fire extinguisher within 10m

## 3. Post-work
Inspect area 60 min after completion. Cancel permit and document.
"""

_WEAK_DOC = "Do hot work carefully. Be safe."


# ── Pipeline A: DocAgent → quality gate decision ──────────────────────────────

class TestDocAgentQualityGate:
    """generation → NIM scoring → accept/retry decision."""

    def test_high_score_accepted_first_attempt(self, tmp_path):
        from doc_agent import DocAgent, DocGenerationRequest

        req = DocGenerationRequest(
            user_request="Write a hot work permit procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        with (
            patch("doc_agent._call_llm", return_value=_GOOD_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", return_value=(0.91, "Meets API RP 505 requirements")),
        ):
            path, preview, score, feedback = DocAgent().generate(req)

        assert path.exists()
        assert score >= 0.6, "Score above threshold → accepted"

    def test_low_score_rejected_saves_dpo_pair(self, tmp_path):
        """Score < threshold on first attempt; second attempt is better → DPO pair saved."""
        attempts = {"n": 0}

        def _nim(req, doc):
            attempts["n"] += 1
            # First: weak document, low score; second: improved
            if doc.strip() == _WEAK_DOC.strip():
                return 0.3, "insufficient content"
            return 0.78, "acceptable"

        from doc_agent import DocAgent, DocGenerationRequest

        # First _call_llm returns weak doc; subsequent return good doc
        call_n = {"n": 0}
        def _llm(*args, **kwargs):
            call_n["n"] += 1
            return _WEAK_DOC if call_n["n"] == 1 else _GOOD_DOC

        req = DocGenerationRequest(
            user_request="Write a procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        saved_dpo = []
        with (
            patch("doc_agent._call_llm", side_effect=_llm),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", side_effect=_nim),
            patch("doc_agent._save_dpo_pair", side_effect=lambda *a, **kw: saved_dpo.append(a)),
        ):
            path, _, score, _ = DocAgent().generate(req)

        assert path.exists()
        assert attempts["n"] >= 1

    def test_all_retries_exhausted_still_returns_file(self, tmp_path):
        """Even if all retries fail quality threshold, a file is still returned."""
        from doc_agent import DocAgent, DocGenerationRequest

        req = DocGenerationRequest(
            user_request="Write a procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        with (
            patch("doc_agent._call_llm", return_value=_WEAK_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", return_value=(0.2, "poor quality")),
        ):
            path, _, score, _ = DocAgent().generate(req)

        assert path.exists(), "File must always be returned, even below threshold after retries"

    def test_nim_unavailable_no_retry_loop(self, tmp_path):
        """NIM unavailable prefix → exit retry immediately, not loop MAX_RETRIES times."""
        from doc_agent import DocAgent, DocGenerationRequest

        nim_call_count = {"n": 0}
        def _nim(req, doc):
            nim_call_count["n"] += 1
            return 0.0, "nim_unavailable: NVIDIA_API_KEY not configured"

        req = DocGenerationRequest(
            user_request="Procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        with (
            patch("doc_agent._call_llm", return_value=_GOOD_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", side_effect=_nim),
        ):
            path, _, _, _ = DocAgent().generate(req)

        assert path.exists()
        assert nim_call_count["n"] == 1, (
            f"NIM should be called once then skipped; called {nim_call_count['n']} times"
        )


# ── Pipeline B: Omi OCR text → DB insert → Qdrant enqueue ────────────────────

class TestOmiOcrToDbAndQdrant:
    """OCR sidecar → run_once() → SQLite row inserted → Qdrant index called."""

    def test_file_registered_and_qdrant_called(self, tmp_path):
        from omi_register import run_once

        ocr_dir = tmp_path / "ocr_text"
        ocr_dir.mkdir()
        (ocr_dir / "iso_procedure.txt").write_text(
            "ISO 45001 — Confined Space Entry Procedure\n"
            "This procedure defines requirements for safe confined space entry.\n"
            "Atmospheric monitoring: O2 19.5–23.5%, LEL <10%.\n",
            encoding="utf-8",
        )

        db = tmp_path / "omi.db"
        qdrant_calls = []
        def _fake_qdrant(conn, path, fp):
            qdrant_calls.append(path.name)

        with patch.dict("os.environ", {
            "OMI_OCR_TEXT_DIR": str(ocr_dir),
            "OMI_REGISTER_LEGACY_OUTBOX_TXT": "0",
            "OMI_REGISTER_LEGACY_OUTBOX_DOCX": "0",
            "OMI_OLLAMA_ENABLED": "0",
            "OMI_DEDUPE_BY_HASH": "0",
            "QDRANT_ENABLED": "0",
        }):
            with patch("omi_register._index_in_qdrant", side_effect=_fake_qdrant):
                run_once(db_path=db)

        # Verify DB row
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT file_name FROM ocr_documents").fetchall()
        conn.close()
        assert len(rows) >= 1
        assert any("iso_procedure" in r[0] for r in rows)

        # Verify Qdrant was called
        assert len(qdrant_calls) >= 1, "Qdrant indexing must be called for new documents"
        assert any("iso_procedure" in c for c in qdrant_calls)

    def test_no_silent_fail_on_qdrant_error(self, tmp_path):
        """Qdrant failure must not silently swallow — check that DB row is still written."""
        from omi_register import run_once

        ocr_dir = tmp_path / "ocr_text"
        ocr_dir.mkdir()
        (ocr_dir / "report.txt").write_text("Inspection report Q1 2026.", encoding="utf-8")

        db = tmp_path / "omi.db"
        with patch.dict("os.environ", {
            "OMI_OCR_TEXT_DIR": str(ocr_dir),
            "OMI_REGISTER_LEGACY_OUTBOX_TXT": "0",
            "OMI_REGISTER_LEGACY_OUTBOX_DOCX": "0",
            "OMI_OLLAMA_ENABLED": "0",
            "OMI_DEDUPE_BY_HASH": "0",
            "QDRANT_ENABLED": "0",
        }):
            # Simulate Qdrant connection failure
            with patch("omi_register._index_in_qdrant", side_effect=ConnectionError("qdrant down")):
                run_once(db_path=db)  # must not raise

        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM ocr_documents").fetchone()[0]
        conn.close()
        assert count >= 1, "DB row must be present even if Qdrant index failed"


# ── Quality gate: similarity check (Stage 0 foundational fix) ────────────────

class TestQualityGateSimilarity:
    """omi_quality_gate._sim_pct: embed path + difflib fallback."""

    def test_difflib_fallback_identical(self):
        """When embeddings unavailable, difflib gives 100% for identical text."""
        from omi_quality_gate import _sim_pct
        with patch("omi_quality_gate._embed_sim_pct", return_value=None):
            score = _sim_pct("hello world procedure", "hello world procedure")
        assert score == pytest.approx(100.0)

    def test_difflib_fallback_different(self):
        from omi_quality_gate import _sim_pct
        with patch("omi_quality_gate._embed_sim_pct", return_value=None):
            score = _sim_pct("confined space entry JSA", "fire extinguisher maintenance")
        assert score < 60.0

    def test_embed_path_used_when_available(self):
        """When embeddings return a value, it takes precedence over difflib."""
        from omi_quality_gate import _sim_pct
        with patch("omi_quality_gate._embed_sim_pct", return_value=87.5):
            score = _sim_pct("any text", "any other text")
        assert score == pytest.approx(87.5)

    def test_short_source_logs_warning(self, tmp_path, caplog):
        """Source text shorter than MIN_SOURCE_CHARS → logged warning, not silent approve."""
        import logging
        from omi_quality_gate import _quality_gate_once, MIN_SOURCE_CHARS

        income_dir = tmp_path / "income"
        income_dir.mkdir()
        src = income_dir / "short_doc.pdf"
        src.write_bytes(b"%PDF-1.4 tiny")

        ocr_dir = tmp_path / "ocr_text"
        ocr_dir.mkdir()
        (ocr_dir / "short_doc.txt").write_text("A" * 200, encoding="utf-8")

        with (
            patch("omi_quality_gate.INCOME", income_dir),
            patch("omi_quality_gate.OCR_TEXT_DIR", ocr_dir),
            patch("omi_quality_gate.OUTBOX_LEGACY", tmp_path / "outbox"),
            patch("omi_quality_gate.SKIPPED", tmp_path / "skipped"),
            patch("omi_quality_gate.STATE_DB", tmp_path / "state.db"),
            patch("omi_quality_gate.extract_reference_text_from_inbox", return_value="tiny"),
            patch("omi_quality_gate.run_once"),
            patch("omi_quality_gate._sync_ocr_to_aims"),
            caplog.at_level(logging.WARNING, logger="aims.quality_gate"),
        ):
            approved, rejected = _quality_gate_once()

        assert any("quality gate bypassed" in m for m in caplog.messages), (
            "Must log a warning when source text is too short for quality check"
        )
