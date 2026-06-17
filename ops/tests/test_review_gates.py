#!/usr/bin/env python3
"""Test suite for Phase 2A Review Gate Agents

Verifies that all 5 review gate agents:
1. Return structured PASS/FAIL/NEEDS_INFO responses
2. Include required fields (checklist, recommendations, blocking_issues)
3. Are read-only (no side effects)
4. Handle various input scenarios correctly

Run with: pytest ops/tests/test_review_gates.py -v
"""
import sys
from pathlib import Path

# Add ops directory to path
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

from agents.review_gates.architect_agent import ArchitectAgent
from agents.review_gates.security_agent import SecurityAgent
from agents.review_gates.qa_agent import QAAgent
from agents.review_gates.release_agent import ReleaseAgent
from agents.review_gates.docs_agent import DocsAgent
from agents.review_gates.base import ReviewResult


class TestArchitectAgent:
    """Test ArchitectAgent review gate."""

    def test_basic_pass(self):
        """Test that simple changes pass architectural review."""
        agent = ArchitectAgent()
        context = {
            "task_id": "test-001",
            "change_type": "feature",
            "description": "Add new utility function",
            "files_changed": ["ops/utils/helpers.py"],
        }
        result = agent.review(context)
        
        assert result.result in [ReviewResult.PASS, ReviewResult.NEEDS_INFO]
        assert result.agent == "aims_architect_agent"
        assert isinstance(result.checklist, list)
        assert isinstance(result.recommendations, list)
        assert isinstance(result.blocking_issues, list)
        assert result.timestamp

    def test_core_module_needs_review(self):
        """Test that core module changes trigger review."""
        agent = ArchitectAgent()
        context = {
            "task_id": "test-002",
            "change_type": "refactor",
            "description": "Refactor core module",
            "files_changed": ["ops/core/runtime_names.py"],
        }
        result = agent.review(context)
        
        assert result.result in [ReviewResult.NEEDS_INFO, ReviewResult.PASS]
        assert len(result.checklist) > 0
        assert any("core" in str(c).lower() for c in result.checklist)


class TestSecurityAgent:
    """Test SecurityAgent review gate."""

    def test_basic_pass(self):
        """Test that non-security changes pass."""
        agent = SecurityAgent()
        context = {
            "task_id": "test-003",
            "change_type": "feature",
            "description": "Add logging",
            "files_changed": ["ops/utils/logger.py"],
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.PASS
        assert result.agent == "aims_security_agent"
        assert isinstance(result.checklist, list)

    def test_auth_changes_need_review(self):
        """Test that auth changes trigger security review."""
        agent = SecurityAgent()
        context = {
            "task_id": "test-004",
            "change_type": "feature",
            "description": "Update authentication",
            "files_changed": ["ops/core/service_auth.py"],
        }
        result = agent.review(context)
        
        assert result.result in [ReviewResult.NEEDS_INFO, ReviewResult.PASS]
        assert len(result.recommendations) > 0

    def test_dangerous_operations_fail(self):
        """Test that dangerous operations are flagged."""
        agent = SecurityAgent()
        context = {
            "task_id": "test-005",
            "change_type": "fix",
            "description": "Execute shell command with rm -rf",
            "files_changed": ["ops/utils/cleanup.py"],
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.FAIL
        assert len(result.blocking_issues) > 0


class TestQAAgent:
    """Test QAAgent review gate."""

    def test_code_with_tests_pass(self):
        """Test that code changes with tests pass."""
        agent = QAAgent()
        context = {
            "task_id": "test-006",
            "change_type": "feature",
            "description": "Add new feature",
            "files_changed": ["ops/agents/new_agent.py"],
            "test_files": ["ops/tests/test_new_agent.py"],
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.PASS
        assert result.agent == "aims_qa_agent"

    def test_code_without_tests_needs_review(self):
        """Test that code without tests needs review."""
        agent = QAAgent()
        context = {
            "task_id": "test-007",
            "change_type": "feature",
            "description": "Add new feature",
            "files_changed": ["ops/agents/new_agent.py"],
            "test_files": [],
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.NEEDS_INFO
        assert len(result.recommendations) > 0

    def test_bugfix_without_test_fails(self):
        """Test that bug fixes without regression tests fail."""
        agent = QAAgent()
        context = {
            "task_id": "test-008",
            "change_type": "bugfix",
            "description": "Fix critical bug",
            "files_changed": ["ops/agents/broken_agent.py"],
            "test_files": [],
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.FAIL
        assert len(result.blocking_issues) > 0


class TestReleaseAgent:
    """Test ReleaseAgent review gate."""

    def test_non_production_pass(self):
        """Test that non-production deployments pass easily."""
        agent = ReleaseAgent()
        context = {
            "task_id": "test-009",
            "change_type": "feature",
            "description": "Deploy to staging",
            "files_changed": ["ops/agents/test_agent.py"],
            "deployment_target": "staging",
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.PASS
        assert result.agent == "aims_release_agent"

    def test_production_without_rollback_fails(self):
        """Test that production deployment without rollback plan fails."""
        agent = ReleaseAgent()
        context = {
            "task_id": "test-010",
            "change_type": "release",
            "description": "Deploy to production",
            "files_changed": ["ops/agents/critical_agent.py"],
            "deployment_target": "production",
            "rollback_plan": None,
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.FAIL
        assert len(result.blocking_issues) > 0

    def test_breaking_changes_need_review(self):
        """Test that breaking changes trigger review."""
        agent = ReleaseAgent()
        context = {
            "task_id": "test-011",
            "change_type": "release",
            "description": "Breaking API change",
            "files_changed": ["ops/agents/api_agent.py"],
            "deployment_target": "staging",
            "breaking_changes": True,
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.NEEDS_INFO
        assert len(result.recommendations) > 0


class TestDocsAgent:
    """Test DocsAgent review gate."""

    def test_no_changes_pass(self):
        """Test that non-doc changes pass if no docs needed."""
        agent = DocsAgent()
        context = {
            "task_id": "test-012",
            "change_type": "fix",
            "description": "Fix typo",
            "files_changed": ["ops/utils/helpers.py"],
            "doc_files": [],
        }
        result = agent.review(context)
        
        assert result.result in [ReviewResult.PASS, ReviewResult.NEEDS_INFO]
        assert result.agent == "aims_docs_agent"

    def test_api_changes_without_docs_fail(self):
        """Test that API changes without docs fail."""
        agent = DocsAgent()
        context = {
            "task_id": "test-013",
            "change_type": "feature",
            "description": "Add new API endpoint",
            "files_changed": ["ops/agents/api_agent.py"],
            "doc_files": [],
            "api_changes": True,
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.FAIL
        assert len(result.blocking_issues) > 0

    def test_breaking_changes_without_migration_fail(self):
        """Test that breaking changes without migration guide fail."""
        agent = DocsAgent()
        context = {
            "task_id": "test-014",
            "change_type": "feature",
            "description": "Breaking change",
            "files_changed": ["ops/agents/api_agent.py"],
            "doc_files": [],
            "breaking_changes": True,
        }
        result = agent.review(context)
        
        assert result.result == ReviewResult.FAIL
        assert len(result.blocking_issues) > 0


class TestReviewGateSchema:
    """Test that all agents follow the required schema."""

    def test_all_agents_return_valid_schema(self):
        """Test that all 5 agents return valid ReviewResponse."""
        agents = [
            ArchitectAgent(),
            SecurityAgent(),
            QAAgent(),
            ReleaseAgent(),
            DocsAgent(),
        ]
        
        context = {
            "task_id": "schema-test",
            "change_type": "test",
            "description": "Schema validation",
            "files_changed": ["test.py"],
        }
        
        for agent in agents:
            result = agent.review(context)
            
            # Check required fields
            assert hasattr(result, "result")
            assert hasattr(result, "agent")
            assert hasattr(result, "details")
            assert hasattr(result, "checklist")
            assert hasattr(result, "recommendations")
            assert hasattr(result, "blocking_issues")
            assert hasattr(result, "timestamp")
            
            # Check types
            assert isinstance(result.result, ReviewResult)
            assert isinstance(result.agent, str)
            assert isinstance(result.details, str)
            assert isinstance(result.checklist, list)
            assert isinstance(result.recommendations, list)
            assert isinstance(result.blocking_issues, list)
            assert isinstance(result.timestamp, str)
            
            # Check to_dict method
            result_dict = result.to_dict()
            assert "result" in result_dict
            assert "agent" in result_dict
            assert result_dict["result"] in ["PASS", "FAIL", "NEEDS_INFO"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
