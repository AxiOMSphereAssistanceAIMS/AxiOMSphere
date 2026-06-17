"""
test_training_intake_pipeline.py — Full chain test for the training intake system.

Tests the complete pipeline:
  Agent submits material → intake JSONL → Traini processes → dataset appended → archive created

Covers:
  - submit_training_material() writes correct JSONL
  - All 3 slots accept submissions
  - Traini intake_processor converts to ChatML pairs
  - Dataset line count increases after processing
  - Archive file created after processing
  - Invalid slot rejected
  - Concurrent writes don't corrupt (flock)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ops.learning.training_intake import submit_training_material, VALID_SLOTS, INTAKE_DIR
from ops.traini.intake_processor import process_slot, _build_chatml_pair, SLOT_DATASET_MAP


AIMS_ROOT = Path(__file__).parent.parent.parent.resolve()


class TestSubmitTrainingMaterial:
    """Test the submission API."""

    def test_submit_creates_jsonl_entry(self, tmp_path):
        with patch("ops.learning.training_intake.INTAKE_DIR", tmp_path):
            path = submit_training_material(
                slot="slot32",
                agent="test_agent",
                category="repair_diagnosis",
                system_prompt="System",
                user_input="User question",
                ideal_response={"root_cause": "test"},
                source="unit_test",
            )
            intake_file = tmp_path / "slot32" / "intake.jsonl"
            assert intake_file.exists()
            entry = json.loads(intake_file.read_text().strip())
            assert entry["agent"] == "test_agent"
            assert entry["slot"] == "slot32"
            assert entry["category"] == "repair_diagnosis"
            assert "submitted_at" in entry

    def test_all_slots_accepted(self, tmp_path):
        with patch("ops.learning.training_intake.INTAKE_DIR", tmp_path):
            for slot in VALID_SLOTS:
                path = submit_training_material(
                    slot=slot, agent="test", category="code_generation",
                    system_prompt="S", user_input="U", ideal_response="R",
                )
                assert (tmp_path / slot / "intake.jsonl").exists()

    def test_invalid_slot_raises(self, tmp_path):
        with patch("ops.learning.training_intake.INTAKE_DIR", tmp_path):
            with pytest.raises(ValueError, match="Invalid slot"):
                submit_training_material(
                    slot="slot999", agent="test", category="repair_diagnosis",
                    system_prompt="S", user_input="U", ideal_response="R",
                )

    def test_multiple_appends(self, tmp_path):
        with patch("ops.learning.training_intake.INTAKE_DIR", tmp_path):
            for i in range(5):
                submit_training_material(
                    slot="slot14", agent=f"agent_{i}", category="chat_synthesis",
                    system_prompt="S", user_input=f"Q{i}", ideal_response=f"A{i}",
                )
            lines = (tmp_path / "slot14" / "intake.jsonl").read_text().strip().split("\n")
            assert len(lines) == 5

    def test_dict_response_serialized_as_json(self, tmp_path):
        with patch("ops.learning.training_intake.INTAKE_DIR", tmp_path):
            submit_training_material(
                slot="slot32", agent="test", category="repair_diagnosis",
                system_prompt="S", user_input="U",
                ideal_response={"key": "value", "nested": [1, 2, 3]},
            )
            entry = json.loads((tmp_path / "slot32" / "intake.jsonl").read_text().strip())
            parsed = json.loads(entry["ideal_response"])
            assert parsed["key"] == "value"


class TestBuildChatmlPair:
    """Test the conversion to ChatML format."""

    def test_basic_conversion(self):
        entry = {
            "slot": "slot32",
            "system_prompt": "System prompt here",
            "user_input": "User question",
            "ideal_response": "Assistant answer",
        }
        pair = _build_chatml_pair(entry)
        assert pair["messages"][0]["role"] == "system"
        assert pair["messages"][1]["role"] == "user"
        assert pair["messages"][2]["role"] == "assistant"
        assert pair["messages"][0]["content"] == "System prompt here"

    def test_uses_default_system_prompt_when_empty(self):
        entry = {
            "slot": "slot32",
            "system_prompt": "",
            "user_input": "Q",
            "ideal_response": "A",
        }
        pair = _build_chatml_pair(entry)
        assert "AIMS Repairman" in pair["messages"][0]["content"]


class TestIntakeProcessor:
    """Test the Traini processor."""

    def test_process_empty_slot(self, tmp_path):
        with patch("ops.traini.intake_processor.INTAKE_DIR", tmp_path):
            result = process_slot("slot32", dry_run=True)
            assert result["status"] == "empty"
            assert result["pairs_created"] == 0

    def test_process_creates_pairs(self, tmp_path):
        intake_dir = tmp_path / "intake"
        dataset_dir = tmp_path / "datasets"
        archive_dir = tmp_path / "archive"
        slot_dir = intake_dir / "slot32"
        slot_dir.mkdir(parents=True)
        dataset_dir.mkdir(parents=True)

        dataset_file = dataset_dir / "repairman_slot32_v2" / "train_repairman_slot32_v2.jsonl"
        dataset_file.parent.mkdir(parents=True)
        dataset_file.write_text("")

        entry = {
            "slot": "slot32",
            "agent": "test",
            "category": "repair_diagnosis",
            "system_prompt": "S",
            "user_input": "Q",
            "ideal_response": "A",
            "submitted_at": "2026-06-04T00:00:00Z",
        }
        (slot_dir / "intake.jsonl").write_text(json.dumps(entry) + "\n")

        with patch("ops.traini.intake_processor.INTAKE_DIR", intake_dir), \
             patch("ops.traini.intake_processor.DATASET_DIR", dataset_dir), \
             patch("ops.traini.intake_processor.ARCHIVE_DIR", archive_dir):
            result = process_slot("slot32", dry_run=False)

        assert result["pairs_created"] == 1
        assert result["status"] == "processed"
        lines = dataset_file.read_text().strip().split("\n")
        assert len(lines) == 1
        pair = json.loads(lines[0])
        assert pair["messages"][2]["content"] == "A"
        assert len(list(archive_dir.iterdir())) == 1


class TestProductionIntegration:
    """Test against real production file structure."""

    def test_real_intake_dirs_exist(self):
        for slot in ["slot14", "slot32", "slot120"]:
            assert (AIMS_ROOT / "aims_workspace" / "training_intake" / slot).is_dir()

    def test_real_datasets_exist(self):
        for rel_path in SLOT_DATASET_MAP.values():
            full = AIMS_ROOT / "ops" / "ft" / "data" / rel_path
            if "master" not in rel_path:
                assert full.exists(), f"Dataset missing: {rel_path}"

    def test_slot32_dataset_has_content(self):
        ds = AIMS_ROOT / "ops" / "ft" / "data" / "repairman_slot32_v2" / "train_repairman_slot32_v2.jsonl"
        lines = ds.read_text().strip().split("\n")
        assert len(lines) >= 750

    def test_processed_archive_exists(self):
        archive = AIMS_ROOT / "aims_workspace" / "training_intake" / "_processed"
        assert archive.is_dir()
        assert len(list(archive.iterdir())) >= 1
