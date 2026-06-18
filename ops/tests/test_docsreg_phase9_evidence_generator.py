"""Tests for PHASE 9 Evidence Generator."""
import json
import pytest
from dataclasses import asdict

from ops.docsreg.dataset_qa.evidence_generator import DatasetEvidenceGenerator
from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    DatasetManifest,
    DatasetQualityReport,
    DeduplicationResult,
    BalanceReport,
    LeakageFinding,
    LeakageType,
)


def _make_example(example_id="ex1", **kw) -> TrainingExample:
    import hashlib
    defaults = dict(
        example_id=example_id, document_id="doc1", archetype="tr",
        failure_class="fc1", skill_id="sk1", skill_version="v1",
        source_text="src", failure_context="ctx", repair_instruction="fix",
        repaired_text="rep", quality_before=0.7, quality_after=0.95,
        quality_delta=0.25, data_retention_rate=0.995, data_loss_percentage=0.5,
        required_field_preservation_rate=1.0, section_preservation_rate=0.99,
        retention_verdict="PASS", repair_verdict="PROMOTED",
        input_sha256=hashlib.sha256(f"in_{example_id}".encode()).hexdigest(),
        output_sha256=hashlib.sha256(f"out_{example_id}".encode()).hexdigest(),
        created_at="2026-06-18T12:00:00+00:00",
    )
    defaults.update(kw)
    return TrainingExample(**defaults)


class TestEvidenceGenerator:
    def test_output_dir_created(self, tmp_path):
        out = tmp_path / "output"
        gen = DatasetEvidenceGenerator(out)
        assert out.exists()

    def test_generate_all_creates_9_files(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        files = gen.generate_all(
            training_set=[_make_example("t1")],
            validation_set=[_make_example("v1")],
            rejected_examples=[],
            manifest=DatasetManifest(training_count=1, validation_count=1),
            quality_report=DatasetQualityReport(
                total_examples_processed=2,
                passes_quality_gate=True,
                readiness_checklist={"all_tests": True},
            ),
            leakage_findings=[],
            dedup_result=DeduplicationResult(
                total_before=2, total_after=2, duplicates_removed=0,
                exact_duplicates=0, normalized_duplicates=0,
                near_duplicates=0, same_doc_class_output=0,
            ),
            balance_report=BalanceReport(total_examples=2, passes_balance_gate=True),
        )
        assert len(files) == 9
        for f in files:
            assert f.exists()

    def test_training_jsonl_content(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        ex = _make_example("t1")
        gen.generate_all(
            training_set=[ex], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(readiness_checklist={}),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        jsonl_path = tmp_path / "docsreg_phase9_training_dataset.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["example_id"] == "t1"

    def test_manifest_json_valid(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(phase="PHASE_9", training_count=0),
            quality_report=DatasetQualityReport(readiness_checklist={}),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        manifest = json.loads((tmp_path / "docsreg_phase9_dataset_manifest.json").read_text())
        assert manifest["phase"] == "PHASE_9"

    def test_leakage_report_with_findings(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        findings = [
            LeakageFinding(
                leakage_type=LeakageType.EMAIL,
                field_name="source_text",
                matched_text="user@test.com",
                replacement="[EMAIL]",
                position=10,
            ),
        ]
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(readiness_checklist={}),
            leakage_findings=findings, dedup_result=None, balance_report=None,
        )
        report = json.loads((tmp_path / "docsreg_phase9_leakage_report.json").read_text())
        assert report["total_findings"] == 1
        assert "email" in report["findings_by_type"]

    def test_dedup_report_not_run(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(readiness_checklist={}),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        report = json.loads((tmp_path / "docsreg_phase9_deduplication_report.json").read_text())
        assert report["status"] == "not_run"

    def test_readiness_checklist_verdict(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(
                passes_quality_gate=True,
                readiness_checklist={"test_gate": True},
            ),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        checklist = json.loads((tmp_path / "docsreg_phase9_readiness_checklist.json").read_text())
        assert checklist["overall_verdict"] == "READY"

    def test_readiness_checklist_not_ready(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(
                passes_quality_gate=False,
                readiness_checklist={"gate": False},
            ),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        checklist = json.loads((tmp_path / "docsreg_phase9_readiness_checklist.json").read_text())
        assert checklist["overall_verdict"] == "NOT_READY"

    def test_empty_jsonl_for_no_examples(self, tmp_path):
        gen = DatasetEvidenceGenerator(tmp_path)
        gen.generate_all(
            training_set=[], validation_set=[], rejected_examples=[],
            manifest=DatasetManifest(),
            quality_report=DatasetQualityReport(readiness_checklist={}),
            leakage_findings=[], dedup_result=None, balance_report=None,
        )
        content = (tmp_path / "docsreg_phase9_training_dataset.jsonl").read_text()
        assert content == ""
