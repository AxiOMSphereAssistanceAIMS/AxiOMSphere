"""Tests for PHASE 9 Example Builder."""
import json
import pytest
from pathlib import Path

from ops.docsreg.dataset_qa.example_builder import ExampleBuilder
from ops.docsreg.dataset_qa.models import TrainingExample


def _sample_record(**overrides):
    rec = dict(
        document_id="doc_001",
        archetype="technical_report",
        failure_class="missing_header",
        skill_id="fix_structure",
        skill_version="v2",
        source_text="Source document with issues",
        failure_context="Header section missing",
        repair_instruction="Add required header",
        repaired_text="Source document with proper header added",
        quality_before=0.65,
        quality_after=0.92,
        data_retention_rate=0.995,
        data_loss_percentage=0.5,
        required_field_preservation_rate=1.0,
        section_preservation_rate=0.99,
        retention_verdict="PASS",
        repair_verdict="PROMOTED",
    )
    rec.update(overrides)
    return rec


class TestExampleBuilder:
    def test_build_single(self):
        builder = ExampleBuilder()
        ex = builder.build_single(
            document_id="doc_001",
            archetype="technical_report",
            failure_class="missing_header",
            skill_id="fix_structure",
            skill_version="v1",
            source_text="broken",
            failure_context="ctx",
            repair_instruction="fix it",
            repaired_text="fixed",
            quality_before=0.60,
            quality_after=0.90,
            data_retention_rate=0.99,
            data_loss_percentage=1.0,
            required_field_preservation_rate=1.0,
            section_preservation_rate=0.99,
            retention_verdict="PASS",
            repair_verdict="PROMOTED",
        )
        assert isinstance(ex, TrainingExample)
        assert ex.quality_delta == 0.30
        assert len(ex.input_sha256) == 64
        assert len(ex.output_sha256) == 64
        assert ex.input_sha256 != ex.output_sha256
        assert ex.example_id.startswith("ex_doc_001_missing_header_")

    def test_build_from_records(self):
        builder = ExampleBuilder()
        records = [_sample_record(), _sample_record(document_id="doc_002")]
        examples = builder.build_from_records(records)
        assert len(examples) == 2
        doc_ids = {ex.document_id for ex in examples}
        assert doc_ids == {"doc_001", "doc_002"}

    def test_build_from_records_skips_empty(self):
        builder = ExampleBuilder()
        records = [
            _sample_record(),
            _sample_record(source_text=""),  # empty source
            _sample_record(repaired_text=""),  # empty repair
        ]
        examples = builder.build_from_records(records)
        assert len(examples) == 1

    def test_quality_delta_computed(self):
        builder = ExampleBuilder()
        ex = builder.build_single(
            document_id="d", archetype="a", failure_class="fc",
            skill_id="s", skill_version="v1",
            source_text="src", failure_context="", repair_instruction="",
            repaired_text="rep",
            quality_before=0.50, quality_after=0.80,
            data_retention_rate=0.99, data_loss_percentage=1.0,
            required_field_preservation_rate=1.0, section_preservation_rate=0.99,
            retention_verdict="PASS", repair_verdict="PROMOTED",
        )
        assert ex.quality_delta == pytest.approx(0.30, abs=0.001)

    def test_sha256_hashes_correct(self):
        import hashlib
        builder = ExampleBuilder()
        ex = builder.build_single(
            document_id="d", archetype="a", failure_class="fc",
            skill_id="s", skill_version="v1",
            source_text="hello world", failure_context="", repair_instruction="",
            repaired_text="hello fixed world",
            quality_before=0.5, quality_after=0.8,
            data_retention_rate=0.99, data_loss_percentage=1.0,
            required_field_preservation_rate=1.0, section_preservation_rate=0.99,
            retention_verdict="PASS", repair_verdict="PROMOTED",
        )
        expected_in = hashlib.sha256(b"hello world").hexdigest()
        expected_out = hashlib.sha256(b"hello fixed world").hexdigest()
        assert ex.input_sha256 == expected_in
        assert ex.output_sha256 == expected_out

    def test_build_from_evidence(self, tmp_path):
        skill_results = {
            "fix_structure": {
                "cases": [
                    {
                        "document_id": "doc_A",
                        "archetype": "technical_report",
                        "failure_class": "missing_header",
                        "skill_version": "v1",
                        "source_text": "broken doc",
                        "failure_context": "header absent",
                        "repair_instruction": "add header",
                        "repaired_text": "fixed doc with header",
                        "quality_before": 0.60,
                        "quality_after": 0.85,
                        "data_retention_rate": 0.99,
                        "data_loss_percentage": 1.0,
                        "required_field_preservation_rate": 1.0,
                        "section_preservation_rate": 0.99,
                        "retention_verdict": "PASS",
                        "repair_verdict": "PROMOTED",
                    }
                ]
            }
        }
        results_file = tmp_path / "skill_results.json"
        results_file.write_text(json.dumps(skill_results))

        builder = ExampleBuilder()
        examples = builder.build_from_evidence(tmp_path)
        assert len(examples) == 1
        assert examples[0].skill_id == "fix_structure"
        assert examples[0].document_id == "doc_A"

    def test_build_from_evidence_empty(self, tmp_path):
        builder = ExampleBuilder()
        examples = builder.build_from_evidence(tmp_path)
        assert examples == []

    def test_examples_property(self):
        builder = ExampleBuilder()
        builder.build_from_records([_sample_record()])
        assert len(builder.examples) == 1
        # Verify it returns a copy
        builder.examples.clear()
        assert len(builder.examples) == 1
