#!/usr/bin/env python3
"""Tests for review gate logic — deterministic pure functions.

Tests call review_gates.py functions directly (no HTTP server required).
Covers all blocking rules (A1-A3, S1-S4, Q1-Q3, R1-R3, D1-D2)
and the run_all_reviews aggregator.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest

from self_healing.review_gates import (
    ReviewResult,
    architect_review,
    security_review,
    qa_review,
    release_review,
    docs_review,
    run_all_reviews,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean() -> dict:
    """Minimal passing proposal."""
    return {
        "files_changed": ["ops/agents/some_agent.py"],
        "patch_diff": "- old line\n+ new line\n",
        "risk_level": "low",
        "root_cause": "Fixed null pointer in agent startup",
        "restorative": True,
        "concept_preserved": True,
        "test_result": "pass",
        "rollback_notes": "git revert HEAD",
    }


# ---------------------------------------------------------------------------
# ReviewResult
# ---------------------------------------------------------------------------

class TestReviewResult:
    def test_to_dict_keys(self):
        r = ReviewResult(approved=True, concerns=[], score=0.9, reviewer="qa")
        d = r.to_dict()
        assert set(d.keys()) == {"approved", "concerns", "score", "reviewer"}

    def test_score_clamped_above(self):
        r = ReviewResult(approved=True, score=2.0)
        assert r.to_dict()["score"] == 1.0

    def test_score_clamped_below(self):
        r = ReviewResult(approved=False, score=-5.0)
        assert r.to_dict()["score"] == 0.0

    def test_score_rounded(self):
        r = ReviewResult(approved=True, score=0.999999)
        assert r.to_dict()["score"] == 1.0


# ---------------------------------------------------------------------------
# Architect review
# ---------------------------------------------------------------------------

class TestArchitectReview:
    def test_clean_proposal_passes(self):
        r = architect_review(_clean())
        assert r.approved is True
        assert r.score == 1.0
        assert r.reviewer == "architect"

    def test_A1_core_arch_without_restorative_blocks(self):
        p = _clean()
        p["files_changed"] = ["ops/core/queue.py"]
        p["restorative"] = False
        r = architect_review(p)
        assert r.approved is False
        assert any("restorative" in c for c in r.concerns)
        assert r.score <= 0.5

    def test_A1_core_arch_with_restorative_passes(self):
        p = _clean()
        p["files_changed"] = ["ops/core/queue.py"]
        p["restorative"] = True
        r = architect_review(p)
        assert r.approved is True

    def test_A2_high_risk_no_concept_blocks(self):
        p = _clean()
        p["risk_level"] = "high"
        p["concept_preserved"] = False
        r = architect_review(p)
        assert r.approved is False
        assert any("concept" in c for c in r.concerns)

    def test_A2_high_risk_with_concept_passes(self):
        p = _clean()
        p["risk_level"] = "high"
        p["concept_preserved"] = True
        r = architect_review(p)
        assert r.approved is True

    def test_A3_cross_subsystem_advisory_does_not_block(self):
        p = _clean()
        # Touch 3+ subsystems
        p["files_changed"] = [
            "ops/agents/poli_agent.py",
            "ops/agents/knomi_agent.py",
            "ops/argus/argus_bot.py",
            "ops/agents/mainy_repair_agent.py",
        ]
        r = architect_review(p)
        assert r.approved is True
        assert r.score < 1.0
        assert any("subsystem" in c for c in r.concerns)

    def test_A3_two_subsystems_no_warning(self):
        p = _clean()
        p["files_changed"] = ["ops/agents/poli_agent.py", "ops/agents/knomi_agent.py"]
        r = architect_review(p)
        assert r.approved is True
        assert not any("subsystem" in c for c in r.concerns)

    def test_docker_compose_is_core_arch_file(self):
        p = _clean()
        p["files_changed"] = ["docker-compose.yml"]
        p["restorative"] = False
        r = architect_review(p)
        assert r.approved is False


# ---------------------------------------------------------------------------
# Security review
# ---------------------------------------------------------------------------

class TestSecurityReview:
    def test_clean_proposal_passes(self):
        r = security_review(_clean())
        assert r.approved is True
        assert r.reviewer == "security"

    def test_S1_rm_rf_blocks(self):
        p = _clean()
        p["patch_diff"] = "+    rm -rf /tmp/workdir"
        r = security_review(p)
        assert r.approved is False
        assert any("dangerous" in c for c in r.concerns)

    def test_S1_os_system_blocks(self):
        p = _clean()
        p["patch_diff"] = "+    os.system('ls')"
        r = security_review(p)
        assert r.approved is False

    def test_S1_eval_blocks(self):
        p = _clean()
        p["patch_diff"] = "+    result = eval(user_input)"
        r = security_review(p)
        assert r.approved is False

    def test_S1_exec_blocks(self):
        p = _clean()
        p["patch_diff"] = "+    exec(code_string)"
        r = security_review(p)
        assert r.approved is False

    def test_S1_subprocess_shell_true_blocks(self):
        p = _clean()
        p["patch_diff"] = "+    subprocess.run(cmd, shell=True)"
        r = security_review(p)
        assert r.approved is False

    def test_S2_auth_file_no_restorative_blocks(self):
        p = _clean()
        p["files_changed"] = ["ops/core/service_auth.py"]
        p["restorative"] = False
        r = security_review(p)
        assert r.approved is False
        assert any("auth" in c for c in r.concerns)

    def test_S2_auth_file_with_restorative_passes(self):
        p = _clean()
        p["files_changed"] = ["ops/core/service_auth.py"]
        p["restorative"] = True
        r = security_review(p)
        assert r.approved is True

    def test_S3_high_risk_auth_file_blocks(self):
        p = _clean()
        p["risk_level"] = "high"
        p["files_changed"] = ["ops/core/service_auth.py"]
        p["restorative"] = True
        r = security_review(p)
        assert r.approved is False
        assert any("manual approval" in c for c in r.concerns)

    def test_S4_subprocess_no_shell_advisory(self):
        p = _clean()
        p["patch_diff"] = "+    subprocess.run(['ls', '-la'])"
        r = security_review(p)
        assert r.approved is True
        assert r.score < 1.0
        assert any("subprocess" in c for c in r.concerns)

    def test_env_file_treated_as_auth(self):
        p = _clean()
        p["files_changed"] = [".env"]
        p["restorative"] = False
        r = security_review(p)
        assert r.approved is False


# ---------------------------------------------------------------------------
# QA review
# ---------------------------------------------------------------------------

class TestQAReview:
    def test_clean_proposal_passes(self):
        r = qa_review(_clean())
        assert r.approved is True
        assert r.reviewer == "qa"

    def test_Q1_test_fail_blocks(self):
        p = _clean()
        p["test_result"] = "fail"
        r = qa_review(p)
        assert r.approved is False
        assert any("test failure" in c for c in r.concerns)
        assert r.score < 0.31

    def test_Q2_high_risk_not_run_blocks(self):
        p = _clean()
        p["risk_level"] = "high"
        p["test_result"] = "not_run"
        r = qa_review(p)
        assert r.approved is False
        assert any("no test results" in c for c in r.concerns)

    def test_Q2_high_risk_pass_is_ok(self):
        p = _clean()
        p["risk_level"] = "high"
        p["test_result"] = "pass"
        r = qa_review(p)
        assert r.approved is True

    def test_Q3_medium_risk_py_no_tests_advisory(self):
        p = _clean()
        p["risk_level"] = "medium"
        p["files_changed"] = ["ops/agents/some_agent.py"]
        p["test_result"] = "pass"
        r = qa_review(p)
        assert r.approved is True
        assert r.score < 1.0
        assert any("Python file" in c for c in r.concerns)

    def test_Q3_low_risk_no_advisory(self):
        p = _clean()
        p["risk_level"] = "low"
        p["files_changed"] = ["ops/agents/some_agent.py"]
        r = qa_review(p)
        assert r.approved is True
        assert not any("Python file" in c for c in r.concerns)

    def test_Q3_test_file_included_no_advisory(self):
        p = _clean()
        p["risk_level"] = "medium"
        p["files_changed"] = ["ops/agents/some_agent.py", "ops/tests/test_some_agent.py"]
        r = qa_review(p)
        assert r.approved is True
        assert not any("Python file" in c for c in r.concerns)


# ---------------------------------------------------------------------------
# Release review
# ---------------------------------------------------------------------------

class TestReleaseReview:
    def test_clean_proposal_passes(self):
        r = release_review(_clean())
        assert r.approved is True
        assert r.reviewer == "release"

    def test_R1_docker_compose_blocks(self):
        p = _clean()
        p["files_changed"] = ["docker-compose.yml"]
        r = release_review(p)
        assert r.approved is False
        assert any("docker-compose" in c for c in r.concerns)

    def test_R1_dgx_compose_blocks(self):
        p = _clean()
        p["files_changed"] = ["docker-compose.dgx.yml"]
        r = release_review(p)
        assert r.approved is False

    def test_R2_high_risk_non_restorative_blocks(self):
        p = _clean()
        p["risk_level"] = "high"
        p["restorative"] = False
        r = release_review(p)
        assert r.approved is False
        assert any("non-restorative" in c for c in r.concerns)

    def test_R2_high_risk_restorative_passes(self):
        p = _clean()
        p["risk_level"] = "high"
        p["restorative"] = True
        r = release_review(p)
        assert r.approved is True

    def test_R3_entrypoint_no_rollback_advisory(self):
        p = _clean()
        p["files_changed"] = ["ops/axi_bot.py"]
        p["rollback_notes"] = ""
        r = release_review(p)
        assert r.approved is True
        assert r.score < 1.0
        assert any("rollback" in c for c in r.concerns)

    def test_R3_entrypoint_with_rollback_no_advisory(self):
        p = _clean()
        p["files_changed"] = ["ops/axi_bot.py"]
        p["rollback_notes"] = "git revert HEAD && docker compose restart"
        r = release_review(p)
        assert r.approved is True
        assert not any("rollback" in c for c in r.concerns)

    def test_R3_non_entrypoint_no_advisory(self):
        p = _clean()
        p["files_changed"] = ["ops/agents/some_agent.py"]
        p["rollback_notes"] = ""
        r = release_review(p)
        assert r.approved is True
        assert not any("rollback" in c for c in r.concerns)


# ---------------------------------------------------------------------------
# Docs review
# ---------------------------------------------------------------------------

class TestDocsReview:
    def test_docs_never_blocks(self):
        """docs_review always returns approved=True regardless of input."""
        p = _clean()
        p["files_changed"] = []
        p["patch_diff"] = ""
        r = docs_review(p)
        assert r.approved is True
        assert r.reviewer == "docs"

    def test_D1_py_without_md_advisory(self):
        p = _clean()
        p["files_changed"] = ["ops/agents/some_agent.py"]
        p["patch_diff"] = ""
        r = docs_review(p)
        assert r.approved is True
        assert r.score < 1.0
        assert any("documentation" in c for c in r.concerns)

    def test_D1_py_with_md_no_advisory(self):
        p = _clean()
        p["files_changed"] = ["ops/agents/some_agent.py", "README.md"]
        r = docs_review(p)
        assert r.approved is True
        assert not any("documentation" in c for c in r.concerns)

    def test_D2_new_defs_without_docstrings_advisory(self):
        p = _clean()
        p["files_changed"] = []
        p["patch_diff"] = "+def new_function(x):\n+    return x\n"
        r = docs_review(p)
        assert r.approved is True
        assert any("docstring" in c for c in r.concerns)

    def test_D2_new_defs_with_docstrings_no_advisory(self):
        p = _clean()
        p["files_changed"] = []
        p["patch_diff"] = '+def new_function(x):\n+    """Do the thing."""\n+    return x\n'
        r = docs_review(p)
        assert r.approved is True
        assert not any("docstring" in c for c in r.concerns)

    def test_docs_never_blocks_even_with_all_concerns(self):
        """Worst case: no md, no docstrings — still approved."""
        p = _clean()
        p["files_changed"] = ["ops/agents/some_agent.py"]
        p["patch_diff"] = "+def a():\n+    pass\n+class B:\n+    pass\n"
        r = docs_review(p)
        assert r.approved is True


# ---------------------------------------------------------------------------
# run_all_reviews aggregator
# ---------------------------------------------------------------------------

class TestRunAllReviews:
    def test_clean_proposal_all_pass(self):
        result = run_all_reviews(_clean())
        assert result["approved"] is True
        assert result["score"] > 0.0
        assert set(result["results"].keys()) == {"architect", "security", "qa", "release", "docs"}

    def test_any_blocking_reviewer_denies_aggregate(self):
        p = _clean()
        p["test_result"] = "fail"  # qa blocks
        result = run_all_reviews(p)
        assert result["approved"] is False

    def test_docs_advisory_does_not_block_aggregate(self):
        p = _clean()
        # Only docs will have concerns — py without md — but should still approve
        p["files_changed"] = ["ops/agents/some_agent.py"]
        p["test_result"] = "pass"
        result = run_all_reviews(p)
        assert result["approved"] is True

    def test_score_is_min_across_all(self):
        p = _clean()
        p["risk_level"] = "medium"
        p["files_changed"] = ["ops/agents/some_agent.py"]  # Q3 advisory -0.1, D1 advisory -0.05
        result = run_all_reviews(p)
        assert result["score"] < 1.0

    def test_multi_block_score_very_low(self):
        p = _clean()
        p["test_result"] = "fail"           # Q1 -0.7
        p["patch_diff"] = "+    eval(x)"    # S1 -0.6
        result = run_all_reviews(p)
        assert result["approved"] is False
        assert result["score"] < 0.5

    def test_result_structure(self):
        result = run_all_reviews(_clean())
        for reviewer, rv in result["results"].items():
            assert "approved" in rv
            assert "concerns" in rv
            assert "score" in rv
            assert "reviewer" in rv
            assert rv["reviewer"] == reviewer

    def test_score_clamped_non_negative(self):
        p = _clean()
        p["test_result"] = "fail"
        p["patch_diff"] = "+    eval(x)\n+    exec(y)\n+    os.system('rm -rf /')"
        result = run_all_reviews(p)
        assert result["score"] >= 0.0


# ---------------------------------------------------------------------------
# FastAPI agent imports (smoke — no server required)
# ---------------------------------------------------------------------------

class TestAgentImports:
    def test_architect_agent_imports(self):
        import ops.agents.architect_agent as m
        assert hasattr(m, "app")
        assert hasattr(m, "review")
        assert m.PORT == 8011
        assert m.AGENT_NAME == "architect_agent"

    def test_security_agent_imports(self):
        import ops.agents.security_agent as m
        assert hasattr(m, "app")
        assert m.PORT == 8012
        assert m.AGENT_NAME == "security_agent"

    def test_qa_agent_imports(self):
        import ops.agents.qa_agent as m
        assert hasattr(m, "app")
        assert m.PORT == 8013
        assert m.AGENT_NAME == "qa_agent"

    def test_release_agent_imports(self):
        import ops.agents.release_agent as m
        assert hasattr(m, "app")
        assert m.PORT == 8014
        assert m.AGENT_NAME == "release_agent"

    def test_docs_agent_imports(self):
        import ops.agents.docs_agent as m
        assert hasattr(m, "app")
        assert m.PORT == 8015
        assert m.AGENT_NAME == "docs_agent"

    def test_docs_agent_is_advisory(self):
        import ops.agents.docs_agent as m
        # Health endpoint confirms advisory flag
        result = m.health()
        assert result.get("advisory") is True

    def test_review_gates_module_importable(self):
        from self_healing.review_gates import run_all_reviews, ReviewResult
        assert callable(run_all_reviews)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
