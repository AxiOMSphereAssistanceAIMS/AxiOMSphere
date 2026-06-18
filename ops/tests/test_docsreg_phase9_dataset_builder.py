"""Tests for PHASE 9 Dataset Builder."""
import json
import pytest
from pathlib import Path

from ops.docsreg.dataset_qa.dataset_builder import DatasetBuilder, TRAIN_RATIO
from ops.docsreg.dataset_qa.models import TrainingExample, DatasetManifest


def _make_record(
    doc_id="doc1", failure_class="fc1", skill_id="sk1",
    source="broken text", repaired="fixed text",
    quality_before=0.70, quality_after=0.95,
    retention=0.995, loss=0.5,
    repair_verdict="PROMOTED", retention_verdict="PASS",
):
    return dict(
        document_id=doc_id, archetype="technical_report",
        failure_class=failure_class, skill_id=skill_id, skill_version="v1",
        source_text=source, failure_context="ctx", repair_instruction="fix",
        repaired_text=repaired,
        quality_before=quality_before, quality_after=quality_after,
        data_retention_rate=retention, data_loss_percentage=loss,
        required_field_preservation_rate=1.0, section_preservation_rate=0.99,
        retention_verdict=retention_verdict, repair_verdict=repair_verdict,
    )


class TestDatasetBuilder:
    def test_build_from_records_basic(self):
        records = [
            _make_record(doc_id="d1", source=f"src_{i}", repaired=f"rep_{i}")
            for i in range(5)
        ]
        builder = DatasetBuilder(seed=42)
        manifest = builder.build_from_records(records)
        assert isinstance(manifest, DatasetManifest)
        assert manifest.total_processed == 5

    def test_pipeline_produces_train_and_val(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"source_{i}", repaired=f"repaired_{i}")
            for i in range(10)
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        assert len(builder.training_set) > 0
        assert len(builder.validation_set) > 0
        assert len(builder.training_set) + len(builder.validation_set) <= 10

    def test_no_document_leakage(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"src_{i}", repaired=f"rep_{i}")
            for i in range(10)
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        train_docs = {ex.document_id for ex in builder.training_set}
        val_docs = {ex.document_id for ex in builder.validation_set}
        assert len(train_docs & val_docs) == 0

    def test_split_ratio_approximately_80_20(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"src_{i}", repaired=f"rep_{i}")
            for i in range(20)
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        total = len(builder.training_set) + len(builder.validation_set)
        if total > 0:
            train_ratio = len(builder.training_set) / total
            assert 0.6 <= train_ratio <= 0.95

    def test_rejected_examples_tracked(self):
        records = [
            _make_record(doc_id="d1", source="good_src", repaired="good_rep"),
            _make_record(doc_id="d2", source="bad", repaired="bad", repair_verdict="BLOCKED"),
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        assert len(builder.rejected_examples) >= 1

    def test_leakage_detection_runs(self):
        records = [
            _make_record(doc_id="d1", source="Contact admin@corp.com", repaired="Fixed text"),
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        assert len(builder.leakage_findings) >= 1

    def test_anonymization_applied(self):
        records = [
            _make_record(doc_id="d1", source="Contact admin@corp.com for help", repaired="Fixed document"),
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        for ex in builder.anonymized_examples:
            assert "admin@corp.com" not in ex.source_text

    def test_deduplication_runs(self):
        records = [
            _make_record(doc_id="d1", source="src", repaired="same output"),
            _make_record(doc_id="d2", source="src", repaired="same output"),
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        assert builder.dedup_result is not None

    def test_quality_report_generated(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"src_{i}", repaired=f"rep_{i}")
            for i in range(5)
        ]
        builder = DatasetBuilder(seed=42)
        builder.build_from_records(records)
        assert builder.quality_report is not None
        assert builder.quality_report.total_examples_processed == 5

    def test_manifest_document_ids(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"s_{i}", repaired=f"r_{i}")
            for i in range(6)
        ]
        builder = DatasetBuilder(seed=42)
        manifest = builder.build_from_records(records)
        all_manifest_docs = set(manifest.train_document_ids + manifest.validation_document_ids)
        assert len(all_manifest_docs) > 0

    def test_empty_input(self):
        builder = DatasetBuilder(seed=42)
        manifest = builder.build_from_records([])
        assert manifest.total_processed == 0
        assert manifest.training_count == 0

    def test_seed_reproducibility(self):
        records = [
            _make_record(doc_id=f"doc_{i}", source=f"s_{i}", repaired=f"r_{i}")
            for i in range(10)
        ]
        b1 = DatasetBuilder(seed=42)
        b1.build_from_records(records)
        b2 = DatasetBuilder(seed=42)
        b2.build_from_records(records)
        train1 = sorted(ex.example_id for ex in b1.training_set)
        train2 = sorted(ex.example_id for ex in b2.training_set)
        assert train1 == train2

    def test_build_from_evidence(self, tmp_path):
        skill_results = {
            "fix_structure": {
                "cases": [
                    {
                        "document_id": f"doc_{i}",
                        "archetype": "technical_report",
                        "failure_class": "missing_header",
                        "skill_version": "v1",
                        "source_text": f"broken_{i}",
                        "failure_context": "ctx",
                        "repair_instruction": "fix",
                        "repaired_text": f"fixed_{i}",
                        "quality_before": 0.70,
                        "quality_after": 0.95,
                        "data_retention_rate": 0.995,
                        "data_loss_percentage": 0.5,
                        "required_field_preservation_rate": 1.0,
                        "section_preservation_rate": 0.99,
                        "retention_verdict": "PASS",
                        "repair_verdict": "PROMOTED",
                    }
                    for i in range(5)
                ]
            }
        }
        (tmp_path / "skill_results.json").write_text(json.dumps(skill_results))
        builder = DatasetBuilder(seed=42)
        manifest = builder.build_from_evidence(tmp_path)
        assert manifest.total_processed == 5

    def test_build_from_examples(self):
        from ops.docsreg.dataset_qa.example_builder import ExampleBuilder
        eb = ExampleBuilder()
        examples = [
            eb.build_single(
                document_id=f"d{i}", archetype="tr", failure_class="fc",
                skill_id="sk", skill_version="v1",
                source_text=f"src_{i}", failure_context="", repair_instruction="",
                repaired_text=f"rep_{i}",
                quality_before=0.7, quality_after=0.95,
                data_retention_rate=0.995, data_loss_percentage=0.5,
                required_field_preservation_rate=1.0, section_preservation_rate=0.99,
                retention_verdict="PASS", repair_verdict="PROMOTED",
            )
            for i in range(4)
        ]
        builder = DatasetBuilder(seed=42)
        manifest = builder.build_from_examples(examples)
        assert manifest.total_processed == 4
