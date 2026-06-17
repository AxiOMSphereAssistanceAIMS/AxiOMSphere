"""
Test suite for EvidencePackagerMinimal and evidence staging lifecycle.

Validates pre-decision/final-decision manifest building, completeness validation,
and circular dependency prevention.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from ops.docgen.evidence_packager_minimal import (
    EvidencePackagerMinimal,
    stage_pre_decision_evidence,
    stage_final_decision_evidence,
)


class TestEvidencePackagerMinimal:
    """Test suite for evidence packaging lifecycle."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test artifacts."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def packager(self, temp_dir):
        """Create packager instance."""
        return EvidencePackagerMinimal(temp_dir)

    def test_packager_initialization(self, packager):
        """Test packager initializes with output directory."""
        assert packager.output_dir.exists()
        assert packager.PRE_DECISION_ARTIFACTS == [
            "plan_snapshot",
            "block_graph_final",
            "implementation_log",
        ]
        assert len(packager.FINAL_DECISION_ARTIFACTS) == 5

    def test_build_pre_decision_manifest_empty(self, packager):
        """Test manifest building when no artifacts present."""
        manifest = packager.build_pre_decision_manifest()

        assert len(manifest) == 3
        assert all(v is None for v in manifest.values())

    def test_build_pre_decision_manifest_partial(self, packager, temp_dir):
        """Test manifest building with some artifacts present."""
        # Create two of three pre-decision artifacts
        (temp_dir / "plan_snapshot.json").write_text(json.dumps({"key": "value"}))
        (temp_dir / "block_graph_final.json").write_text(json.dumps({"blocks": []}))

        manifest = packager.build_pre_decision_manifest()

        assert manifest["plan_snapshot"] is not None
        assert manifest["block_graph_final"] is not None
        assert manifest["implementation_log"] is None

    def test_build_pre_decision_manifest_complete(self, packager, temp_dir):
        """Test manifest building with all pre-decision artifacts."""
        for artifact in packager.PRE_DECISION_ARTIFACTS:
            (temp_dir / f"{artifact}.json").write_text(json.dumps({"data": artifact}))

        manifest = packager.build_pre_decision_manifest()

        assert all(v is not None for v in manifest.values())
        assert len(manifest) == 3

    def test_validate_pre_decision_completeness_incomplete(self, packager):
        """Test validation fails when artifacts missing."""
        manifest = packager.build_pre_decision_manifest()
        is_complete, missing = packager.validate_pre_decision_completeness(manifest)

        assert not is_complete
        assert len(missing) == 3

    def test_validate_pre_decision_completeness_complete(self, packager, temp_dir):
        """Test validation passes when all artifacts present."""
        for artifact in packager.PRE_DECISION_ARTIFACTS:
            (temp_dir / f"{artifact}.json").write_text(json.dumps({}))

        manifest = packager.build_pre_decision_manifest()
        is_complete, missing = packager.validate_pre_decision_completeness(manifest)

        assert is_complete
        assert len(missing) == 0

    def test_build_final_decision_manifest_complete(self, packager, temp_dir):
        """Test building final-decision manifest with all artifacts."""
        # Create all 5 final-decision artifacts
        for artifact in packager.FINAL_DECISION_ARTIFACTS:
            (temp_dir / f"{artifact}.json").write_text(json.dumps({"artifact": artifact}))

        manifest = packager.build_final_decision_manifest()

        assert all(v is not None for v in manifest.values())
        assert len(manifest) == 5

    def test_validate_final_decision_completeness_complete(self, packager, temp_dir):
        """Test validation passes when all final artifacts present."""
        for artifact in packager.FINAL_DECISION_ARTIFACTS:
            (temp_dir / f"{artifact}.json").write_text(json.dumps({}))

        manifest = packager.build_final_decision_manifest()
        is_complete, missing = packager.validate_final_decision_completeness(manifest)

        assert is_complete
        assert len(missing) == 0

    def test_save_evidence_package_manifest_pre_decision(self, packager, temp_dir):
        """Test saving pre-decision manifest with metadata."""
        manifest = {"plan_snapshot": str(temp_dir / "plan.json"), "block_graph_final": None, "implementation_log": None}
        manifest_path = packager.save_evidence_package_manifest(manifest, "pre-decision")

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())

        assert data["package_type"] == "pre-decision"
        assert data["completeness"]["total"] == 3
        assert data["completeness"]["present"] == 1
        assert "timestamp" in data

    def test_save_evidence_package_manifest_final_decision(self, packager, temp_dir):
        """Test saving final-decision manifest with metadata."""
        manifest = {
            "plan_snapshot": str(temp_dir / "plan.json"),
            "block_graph_final": str(temp_dir / "graph.json"),
            "implementation_log": str(temp_dir / "log.json"),
            "baseline_eval": str(temp_dir / "eval.json"),
            "final_decision": str(temp_dir / "decision.json"),
        }
        manifest_path = packager.save_evidence_package_manifest(manifest, "final-decision")

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())

        assert data["package_type"] == "final-decision"
        assert data["completeness"]["present"] == 5

    def test_find_artifact_json_extension(self, packager, temp_dir):
        """Test artifact finding with .json extension."""
        (temp_dir / "plan_snapshot.json").write_text("{}")

        manifest = packager.build_pre_decision_manifest()
        assert manifest["plan_snapshot"] == str(temp_dir / "plan_snapshot.json")

    def test_find_artifact_txt_extension(self, packager, temp_dir):
        """Test artifact finding with .txt extension."""
        (temp_dir / "implementation_log.txt").write_text("log content")

        manifest = packager.build_pre_decision_manifest()
        assert manifest["implementation_log"] == str(temp_dir / "implementation_log.txt")

    def test_find_artifact_md_extension(self, packager, temp_dir):
        """Test artifact finding with .md extension."""
        (temp_dir / "block_graph_final.md").write_text("# Graph")

        manifest = packager.build_pre_decision_manifest()
        assert manifest["block_graph_final"] == str(temp_dir / "block_graph_final.md")


class TestStageFunctions:
    """Test suite for helper functions stage_pre_decision_evidence and stage_final_decision_evidence."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_stage_pre_decision_evidence_full(self, temp_dir):
        """Test staging all pre-decision evidence."""
        plan_data = {"model": "axi_omi_sphere", "routes": []}
        graph_data = {"blocks": {"SEC-001": {"type": "SECTION"}}}
        log_data = {"events": [{"timestamp": "2026-06-10T00:00:00Z", "event": "start"}]}

        manifest = stage_pre_decision_evidence(
            temp_dir,
            plan_snapshot=plan_data,
            block_graph_final=graph_data,
            implementation_log=log_data,
        )

        assert len(manifest) == 3
        assert (temp_dir / "plan_snapshot.json").exists()
        assert (temp_dir / "block_graph_final.json").exists()
        assert (temp_dir / "implementation_log.json").exists()

    def test_stage_pre_decision_evidence_partial(self, temp_dir):
        """Test staging partial pre-decision evidence."""
        plan_data = {"model": "axi_omi_sphere"}

        manifest = stage_pre_decision_evidence(
            temp_dir,
            plan_snapshot=plan_data,
            block_graph_final=None,
            implementation_log=None,
        )

        assert len(manifest) == 1
        assert "plan_snapshot" in manifest
        assert (temp_dir / "plan_snapshot.json").exists()
        assert not (temp_dir / "block_graph_final.json").exists()

    def test_stage_final_decision_evidence_complete(self, temp_dir):
        """Test staging final-decision evidence."""
        baseline_eval = {
            "baseline_score": 0.85,
            "metrics": {"content_completeness": 0.9},
            "overall_verdict": "PASS",
        }
        final_decision = {
            "verdict": "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS",
            "baseline_score": 0.85,
            "training_pairs_captured": 3,
            "process_alignment_claimed": True,
            "chatgpt55_quality_claimed": False,
        }

        # First create pre-decision artifacts
        (temp_dir / "plan_snapshot.json").write_text(json.dumps({"plan": "data"}))
        (temp_dir / "block_graph_final.json").write_text(json.dumps({"graph": "data"}))
        (temp_dir / "implementation_log.json").write_text(json.dumps({"log": "data"}))

        # Stage final-decision
        manifest = stage_final_decision_evidence(temp_dir, baseline_eval, final_decision)

        assert len(manifest) == 5
        assert (temp_dir / "baseline_eval.json").exists()
        assert (temp_dir / "final_decision.json").exists()
        assert manifest["plan_snapshot"] is not None

    def test_stage_final_decision_no_circular_dependencies(self, temp_dir):
        """Test that final-decision staging doesn't depend on eval results."""
        baseline_eval = {"score": 0.8}
        final_decision = {"verdict": "PASS"}

        # Should work even if no pre-decision artifacts exist
        manifest = stage_final_decision_evidence(temp_dir, baseline_eval, final_decision)

        # Should save final artifacts regardless
        assert (temp_dir / "baseline_eval.json").exists()
        assert (temp_dir / "final_decision.json").exists()

    def test_evidence_package_manifest_json_structure(self, temp_dir):
        """Test that saved manifest has correct JSON structure."""
        baseline_eval = {"score": 0.85}
        final_decision = {"verdict": "PASS"}

        stage_final_decision_evidence(temp_dir, baseline_eval, final_decision)

        packager = EvidencePackagerMinimal(temp_dir)
        manifest = packager.build_final_decision_manifest()
        manifest_path = packager.save_evidence_package_manifest(manifest, "final-decision")

        data = json.loads(manifest_path.read_text())

        assert "timestamp" in data
        assert "package_type" in data
        assert "artifacts" in data
        assert "completeness" in data
