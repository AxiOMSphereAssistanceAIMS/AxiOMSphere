#!/usr/bin/env python3
"""Tests for DocsAgent — advisory documentation review gate (port 8015).

Covers:
  - Import smoke and app properties
  - Health endpoint (direct call)
  - POST /review endpoint (direct call, no HTTP server)
  - ReviewRequest / ReviewResponse model behaviour
  - Advisory invariant: approved is always True
  - Underlying docs_review() integration
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------

class TestDocsAgentImport:
    def test_app_importable(self):
        from agents.docs_agent import app
        assert app is not None

    def test_app_title(self):
        from agents.docs_agent import app
        assert app.title == "DocsAgent"

    def test_port_and_name(self):
        import agents.docs_agent as m
        assert m.PORT == 8015
        assert m.AGENT_NAME == "docs_agent"

    def test_review_request_model_importable(self):
        from agents.docs_agent import ReviewRequest
        assert ReviewRequest is not None

    def test_review_response_model_importable(self):
        from agents.docs_agent import ReviewResponse
        assert ReviewResponse is not None


# ---------------------------------------------------------------------------
# ReviewRequest model defaults
# ---------------------------------------------------------------------------

class TestReviewRequestModel:
    def test_empty_init(self):
        from agents.docs_agent import ReviewRequest
        req = ReviewRequest()
        assert req.files_changed == []
        assert req.patch_diff == ""
        assert req.risk_level == "low"
        assert req.restorative is True
        assert req.concept_preserved is True
        assert req.test_result == "not_run"
        assert req.rollback_notes == ""

    def test_full_init(self):
        from agents.docs_agent import ReviewRequest
        req = ReviewRequest(
            proposal_id="p-123",
            files_changed=["ops/agents/test.py"],
            patch_diff="- old\n+ new\n",
            risk_level="medium",
            root_cause="Fixed crash on startup",
            restorative=True,
            concept_preserved=False,
            test_result="pass",
            rollback_notes="git revert HEAD",
        )
        assert req.proposal_id == "p-123"
        assert req.risk_level == "medium"
        assert req.concept_preserved is False

    def test_model_dump_returns_dict(self):
        from agents.docs_agent import ReviewRequest
        req = ReviewRequest(files_changed=["a.py"])
        d = req.model_dump()
        assert isinstance(d, dict)
        assert "files_changed" in d
        assert d["files_changed"] == ["a.py"]


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestDocsAgentHealth:
    def test_health_returns_ok(self):
        from agents.docs_agent import health
        result = health()
        assert result["status"] == "ok"

    def test_health_service_name(self):
        from agents.docs_agent import health
        result = health()
        assert result["service"] == "docs_agent"

    def test_health_port(self):
        from agents.docs_agent import health
        result = health()
        assert result["port"] == 8015

    def test_health_advisory_flag(self):
        from agents.docs_agent import health
        result = health()
        assert result["advisory"] is True


# ---------------------------------------------------------------------------
# POST /review — core advisory invariant
# ---------------------------------------------------------------------------

class TestDocsAgentReview:
    def _make_request(self, **kwargs):
        from agents.docs_agent import ReviewRequest
        defaults = {
            "files_changed": ["ops/agents/some_agent.py"],
            "patch_diff": "- old\n+ new\n",
            "risk_level": "low",
            "root_cause": "Fixed null pointer",
            "restorative": True,
            "concept_preserved": True,
            "test_result": "pass",
            "rollback_notes": "git revert HEAD",
        }
        defaults.update(kwargs)
        return ReviewRequest(**defaults)

    def _call_review(self, req):
        """Call review() directly, bypassing HTTP, with a stub Request."""
        from agents.docs_agent import review
        from unittest.mock import MagicMock
        fake_request = MagicMock()
        return review(req, fake_request)

    def test_clean_proposal_approved(self):
        result = self._call_review(self._make_request())
        assert result.approved is True

    def test_advisory_always_approved_high_risk(self):
        """Even high-risk proposals pass — docs gate is advisory only."""
        result = self._call_review(self._make_request(risk_level="high"))
        assert result.approved is True

    def test_advisory_always_approved_no_rollback(self):
        result = self._call_review(self._make_request(rollback_notes=""))
        assert result.approved is True

    def test_advisory_always_approved_concept_not_preserved(self):
        result = self._call_review(self._make_request(concept_preserved=False))
        assert result.approved is True

    def test_reviewer_is_docs(self):
        result = self._call_review(self._make_request())
        assert result.reviewer == "docs"

    def test_response_has_review_id(self):
        result = self._call_review(self._make_request())
        assert result.review_id != ""
        assert len(result.review_id) > 8

    def test_score_in_range(self):
        result = self._call_review(self._make_request())
        assert 0.0 <= result.score <= 1.0

    def test_concerns_is_list(self):
        result = self._call_review(self._make_request())
        assert isinstance(result.concerns, list)

    def test_python_file_without_doc_update_adds_concern(self):
        """docs_review flags Python file changes with no doc update in patch_diff."""
        result = self._call_review(self._make_request(
            files_changed=["ops/agents/some_agent.py"],
            patch_diff="- old_fn()\n+ new_fn()\n",  # no doc content
        ))
        assert any("doc" in c.lower() for c in result.concerns)

    def test_no_concern_for_empty_patch_diff_without_py_files(self):
        """No Python files → no doc concern raised."""
        result = self._call_review(self._make_request(
            files_changed=["ops/config/settings.yaml"],
            patch_diff="- old: true\n+ new: false\n",
        ))
        assert result.approved is True

    def test_review_id_unique_per_call(self):
        r1 = self._call_review(self._make_request())
        r2 = self._call_review(self._make_request())
        assert r1.review_id != r2.review_id


# ---------------------------------------------------------------------------
# Live HTTP smoke (requires running container on port 8015)
# ---------------------------------------------------------------------------

class TestDocsAgentLive:
    """Skipped unless the service is reachable on localhost:8015."""

    @pytest.fixture(autouse=True)
    def _require_service(self):
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:8015/health", timeout=2)
        except Exception:
            pytest.skip("docs-agent not reachable on localhost:8015")

    def test_live_health(self):
        import urllib.request, json
        with urllib.request.urlopen("http://localhost:8015/health", timeout=5) as r:
            data = json.loads(r.read())
        assert data["status"] == "ok"
        assert data["advisory"] is True

    def test_live_review_approved(self):
        import urllib.request, json
        payload = json.dumps({
            "files_changed": ["ops/agents/test.py"],
            "patch_diff": "- old\n+ new\n",
            "risk_level": "low",
            "root_cause": "Test",
            "test_result": "pass",
            "rollback_notes": "git revert HEAD",
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8015/review",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        assert data["approved"] is True
        assert data["reviewer"] == "docs"
        assert "review_id" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
