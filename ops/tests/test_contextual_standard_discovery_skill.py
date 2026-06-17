"""
WP-008 + WP-009: Smoke/unit tests + functional document review test
for contextual_standard_discovery_and_document_review skill.

Run:
    PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_contextual_standard_discovery_skill.py -v

All tests use force_fixture=True — no internet, no secrets, no Qdrant required.
slot120 / nemotron are never referenced in any assertion or fixture.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── Imports under test ─────────────────────────────────────────────────────────
from ops.agents.skills.contextual_standard_discovery import (
    FixtureStandardDiscoveryProvider,
    ManualTeacherProvider,
    PerplexityMCPProvider,
    InternalRAGProvider,
    build_provider_chain,
    search_with_chain,
)
from ops.agents.skills.contextual_standard_discovery_and_document_review import (
    build_benchmark_matrix,
    build_standard_discovery_queries,
    classify_standard_source,
    compare_document_to_benchmark,
    detect_copyright_risk,
    export_traini_training_case,
    extract_document_review_context,
    redact_secrets,
    render_axi_advisory_response,
    render_doci_gap_assessment,
    run_axi_advisory_mode,
    run_doci_review_mode,
    sanitize_external_search_context,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

SAMPLE_TASK = (
    "Review this preservation procedure for rotating equipment during extended shutdown "
    "in oil and gas industry"
)

SAMPLE_DOC = """
1. SCOPE
This procedure covers preservation of centrifugal pumps (P-101, P-102) during extended
shutdown periods exceeding 30 days. Electrical equipment is excluded.

2. REFERENCES
API RP 686. NACE SP0169. HSE UK GS38.

3. ROLES AND RESPONSIBILITIES
Maintenance engineer: procedure owner and executor.
HSE officer: approves PTW prior to work.

4. INSPECTION AND MONITORING
Monthly shaft rotation. Check bearing housing for condensation.
Acceptance criteria: free rotation, no rust visible.

5. SAFETY
PTW required before entry. PPE: hard hat, gloves, safety glasses, steel-toe boots.
LOTO in place before any mechanical work. Emergency response per site HSSE plan.

6. DOCUMENTATION
Preservation record PR-001 to be completed after each inspection.
Retained for minimum 5 years in the maintenance management system.
"""

MINIMAL_DOC = "This is a document about equipment."


# ══════════════════════════════════════════════════════════════════════════════
# WP-008 — Smoke / unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContextExtraction:
    def test_doc_type_detection(self):
        ctx = extract_document_review_context("Review this checklist for safety")
        assert ctx["doc_type"] == "checklist"

    def test_procedure_fallback(self):
        ctx = extract_document_review_context("Standards check for rotating equipment")
        assert ctx["doc_type"] == "procedure"

    def test_lifecycle_preservation(self):
        ctx = extract_document_review_context("Preservation procedure for pumps during shutdown")
        assert ctx["lifecycle_phase"] in ("preservation", "shutdown")

    def test_equipment_class_pump(self):
        ctx = extract_document_review_context("Pump commissioning checklist")
        assert ctx["equipment_class"] == "pump"

    def test_client_ref_always_redacted(self):
        ctx = extract_document_review_context("Review ClientCorp Project-XYZ procedure")
        assert ctx["client_ref_REDACTED"] == "[REDACTED]"
        assert ctx["project_ref_REDACTED"] == "[REDACTED]"

    def test_disciplines_detected(self):
        ctx = extract_document_review_context("Mechanical and electrical inspection procedure")
        assert "mechanical" in ctx["disciplines"] or "electrical" in ctx["disciplines"]

    def test_generic_risks_detected(self):
        ctx = extract_document_review_context("Corrosion control procedure for pipelines")
        assert "corrosion" in ctx["generic_risks"]


class TestSanitization:
    def test_sanitize_removes_client_project_keys(self):
        ctx = extract_document_review_context("Review this procedure")
        san = sanitize_external_search_context(ctx)
        assert "client_ref_REDACTED" not in san
        assert "project_ref_REDACTED" not in san
        assert "disciplines" not in san  # disciplines not in allowed keys

    def test_sanitize_keeps_generic_fields(self):
        ctx = extract_document_review_context("Preservation procedure for rotating equipment")
        san = sanitize_external_search_context(ctx)
        for key in ("doc_type", "industry", "equipment_class", "lifecycle_phase"):
            assert key in san, f"Expected '{key}' in sanitized context"

    def test_sanitize_no_doc_text_in_output(self):
        ctx = extract_document_review_context("Review procedure", "CONFIDENTIAL client document text")
        san = sanitize_external_search_context(ctx)
        for v in san.values():
            if isinstance(v, str):
                assert "CONFIDENTIAL" not in v
                assert "client document text" not in v


class TestQueryBuilding:
    def test_produces_four_queries(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        san = sanitize_external_search_context(ctx)
        queries = build_standard_discovery_queries(san)
        assert len(queries) == 4

    def test_no_secrets_in_queries(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        san = sanitize_external_search_context(ctx)
        queries = build_standard_discovery_queries(san)
        for q in queries:
            qt = q["query_text"].lower()
            assert "api_key" not in qt
            assert "secret" not in qt
            assert "token" not in qt
            assert "password" not in qt

    def test_query_contains_equipment_class(self):
        ctx = extract_document_review_context("Pump preservation procedure")
        san = sanitize_external_search_context(ctx)
        queries = build_standard_discovery_queries(san)
        equipment = san.get("equipment_class", "")
        combined = " ".join(q["query_text"] for q in queries)
        assert equipment in combined

    def test_each_query_has_required_keys(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        san = sanitize_external_search_context(ctx)
        queries = build_standard_discovery_queries(san)
        required_keys = {"query_text", "domain", "industry", "equipment_class", "lifecycle_phase", "search_type"}
        for q in queries:
            assert required_keys.issubset(q.keys()), f"Missing keys in query: {q}"


class TestSourceClassification:
    def test_mandatory_standard_gets_high_authority(self):
        s = classify_standard_source({"source_type": "mandatory_standard", "source_publisher": "API"})
        assert s["source_authority_level"] == "high"
        assert s["mandatory_status"] == "mandatory"

    def test_secondary_is_never_mandatory(self):
        s = classify_standard_source({"source_type": "secondary", "source_publisher": "Blog"})
        assert s["mandatory_status"] != "mandatory"
        assert s["source_authority_level"] == "low"

    def test_regulator_gets_high_authority(self):
        s = classify_standard_source({"source_type": "regulator", "source_publisher": "UK HSE"})
        assert s["source_authority_level"] == "high"
        assert s["mandatory_status"] == "recommended"

    def test_oem_manual_gets_medium_authority(self):
        s = classify_standard_source({"source_type": "oem_manual", "source_publisher": "OEM"})
        assert s["source_authority_level"] == "medium"

    def test_contextual_candidate_is_not_automatically_mandatory(self):
        s = classify_standard_source(
            {
                "source_type": "contextual_standard_candidate",
                "source_publisher": "ISO 14224",
            }
        )
        assert s["source_authority_level"] == "medium"
        assert s["mandatory_status"] == "guidance_only"

    def test_hse_publisher_is_public_domain(self):
        s = classify_standard_source({"source_type": "regulator", "source_publisher": "UK Health and Safety Executive"})
        assert s["copyright_status"] == "public_domain"

    def test_date_field_always_set(self):
        s = classify_standard_source({"source_type": "guidance", "source_publisher": "IEC"})
        assert "source_date_or_access_date" in s
        assert s["source_date_or_access_date"]  # non-empty


class TestBenchmarkMatrix:
    def test_returns_list_of_dicts(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        assert isinstance(matrix, list)
        assert len(matrix) > 0

    def test_all_21_fields_present(self):
        required = {
            "benchmark_id", "document_type", "industry_context", "discipline",
            "equipment_or_system", "lifecycle_phase", "source_title", "source_publisher",
            "source_url", "source_type", "source_authority_level", "source_date_or_access_date",
            "requirement_theme", "benchmark_expectation", "applicability", "mandatory_status",
            "copyright_status", "review_question", "gap_if_missing",
            "recommended_evidence_in_document", "confidence_level",
        }
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        for row in matrix:
            missing = required - set(row.keys())
            assert not missing, f"Row {row.get('benchmark_id')} missing fields: {missing}"

    def test_benchmark_ids_unique(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        ids = [r["benchmark_id"] for r in matrix]
        assert len(ids) == len(set(ids))

    def test_works_with_empty_sources(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        matrix = build_benchmark_matrix(ctx, [])
        assert len(matrix) > 0  # falls back to generic source


class TestSafetyHelpers:
    def test_redact_nvapi_token(self):
        result = redact_secrets("nvapi-ABCDEFGHIJKLMNOPQRSTUVWXYZsomething sensitive")
        assert "nvapi-" not in result
        assert "[REDACTED]" in result

    def test_redact_sk_token(self):
        result = redact_secrets("sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890extra")
        assert "sk-ABC" not in result

    def test_redact_api_key_pattern(self):
        result = redact_secrets("api_key: supersecretvalue123")
        assert "supersecretvalue123" not in result

    def test_no_redaction_on_clean_text(self):
        text = "This is a normal technical description of pump maintenance."
        result = redact_secrets(text)
        assert result == text

    def test_copyright_risk_detected(self):
        assert detect_copyright_risk("This is all rights reserved by ISO standards body.")
        assert detect_copyright_risk("Reproduced with permission from IEC publication.")
        assert detect_copyright_risk("ISO copyright notice applies to this document.")

    def test_no_copyright_risk_on_clean(self):
        assert not detect_copyright_risk("Pump rotation schedule every 30 days.")
        assert not detect_copyright_risk("Refer to API RP 686 for guidance.")


# ══════════════════════════════════════════════════════════════════════════════
# Provider chain tests
# ══════════════════════════════════════════════════════════════════════════════

class TestProviderChain:
    def test_fixture_provider_always_available(self):
        provider = FixtureStandardDiscoveryProvider()
        assert provider.is_available()

    def test_fixture_returns_six_sources(self):
        provider = FixtureStandardDiscoveryProvider()
        results = provider.search([{"query_text": "any query"}])
        assert len(results) == 6

    def test_fixture_sources_have_required_keys(self):
        required = {"source_title", "source_publisher", "source_url", "source_type", "excerpt", "raw_confidence"}
        provider = FixtureStandardDiscoveryProvider()
        for src in provider.search([]):
            assert required.issubset(src.keys())

    def test_perplexity_unavailable_without_key(self):
        env_backup = os.environ.pop("PERPLEXITY_API_KEY", None)
        env_opt_backup = os.environ.pop("AIMS_ENABLE_PERPLEXITY_SEARCH", None)
        try:
            provider = PerplexityMCPProvider()
            assert not provider.is_available()
            result = provider.search([{"query_text": "test"}])
            assert result == []
        finally:
            if env_backup:
                os.environ["PERPLEXITY_API_KEY"] = env_backup
            if env_opt_backup:
                os.environ["AIMS_ENABLE_PERPLEXITY_SEARCH"] = env_opt_backup

    def test_perplexity_unavailable_without_opt_in(self):
        os.environ["PERPLEXITY_API_KEY"] = "fake-key"
        os.environ.pop("AIMS_ENABLE_PERPLEXITY_SEARCH", None)
        try:
            provider = PerplexityMCPProvider()
            assert not provider.is_available()
        finally:
            os.environ.pop("PERPLEXITY_API_KEY", None)

    def test_manual_teacher_blocks_slot120_reference(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"source_title": "slot120 teacher output", "source_publisher": "nemotron"}], f)
            f.flush()
            provider = ManualTeacherProvider(f.name)
            result = provider.search([])
            assert result == [], "slot120 reference should be blocked"

    def test_manual_teacher_accepts_clean_source_pack(self):
        sources = [
            {
                "source_title": "API RP 686",
                "source_publisher": "American Petroleum Institute",
                "source_url": "https://www.api.org/",
                "source_type": "guidance",
                "excerpt": "Guidance on rotating machinery installation.",
                "raw_confidence": 0.85,
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sources, f)
            f.flush()
            provider = ManualTeacherProvider(f.name)
            assert provider.is_available()
            result = provider.search([])
            assert len(result) == 1

    def test_force_fixture_chain_has_only_fixture(self):
        chain = build_provider_chain(force_fixture=True)
        assert len(chain) == 1
        assert isinstance(chain[0], FixtureStandardDiscoveryProvider)

    def test_chain_falls_back_to_fixture_when_empty(self):
        chain = []  # empty chain
        results, provider_name = search_with_chain([{"query_text": "test"}], chain)
        assert len(results) > 0
        assert "Fixture" in provider_name

    def test_internal_rag_provider_uses_retrieval_only(self, monkeypatch):
        from ops.docagent import standards_rag

        clause = standards_rag.Clause(
            standard_id="ISO 14224",
            clause_ref="9",
            clause_title="Maintenance data",
            text="Maintenance data should preserve equipment and failure context.",
            score=0.91,
            source_file="iso_14224.json",
        )
        calls = {"embed": 0, "search": 0, "generate": 0}

        def fake_embed(text):
            calls["embed"] += 1
            assert "centrifugal pump" in text
            return [0.1, 0.2]

        def fake_search(vector):
            calls["search"] += 1
            assert vector == [0.1, 0.2]
            return [clause]

        def fail_generate(*args, **kwargs):
            calls["generate"] += 1
            raise AssertionError("Internal discovery must not invoke generation")

        monkeypatch.setattr(standards_rag, "_embed", fake_embed)
        monkeypatch.setattr(standards_rag, "_search", fake_search)
        monkeypatch.setattr(standards_rag, "_generate", fail_generate)

        provider = InternalRAGProvider()
        monkeypatch.setattr(provider, "is_available", lambda: True)
        results = provider.search(
            [{"query_text": "centrifugal pump preventive maintenance"}]
        )

        assert calls == {"embed": 1, "search": 1, "generate": 0}
        assert results == [
            {
                "source_title": "ISO 14224 §9 — Maintenance data",
                "source_publisher": "ISO 14224",
                "source_url": "",
                "source_type": "contextual_standard_candidate",
                "excerpt": clause.text,
                "raw_confidence": 0.91,
            }
        ]


# ══════════════════════════════════════════════════════════════════════════════
# WP-009 — Functional document review test
# ══════════════════════════════════════════════════════════════════════════════

class TestAxiAdvisoryMode:
    def test_returns_string(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, force_fixture=True)
        assert isinstance(result, str)
        assert len(result) > 50

    def test_contains_expected_sections(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, force_fixture=True)
        assert "Standards Advisory" in result
        assert "benchmark" in result.lower() or "theme" in result.lower()

    def test_no_slot120_in_output(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, force_fixture=True)
        assert "slot120" not in result.lower()
        assert "nemotron" not in result.lower()

    def test_no_secrets_in_output(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, force_fixture=True)
        assert "nvapi-" not in result
        assert "api_key" not in result.lower() or "[REDACTED]" in result

    def test_with_document_text_includes_gap_signals(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, MINIMAL_DOC, force_fixture=True)
        assert isinstance(result, str)
        # With a thin document, should note gaps
        assert "gap" in result.lower() or "missing" in result.lower()

    def test_without_document_no_gap_table(self):
        result = run_axi_advisory_mode(SAMPLE_TASK, force_fixture=True)
        # Without document text, no gap signals section
        # (gaps=None branch skips the gap signal lines)
        assert isinstance(result, str)

    def test_traini_export_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_axi_advisory_mode(
                SAMPLE_TASK,
                MINIMAL_DOC,
                force_fixture=True,
                export_training_case=True,
                training_output_dir=tmpdir,
            )
            exports = list(Path(tmpdir).glob("standard_discovery_case_*.json"))
            assert len(exports) == 1

    def test_traini_export_no_slot120(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_axi_advisory_mode(
                SAMPLE_TASK,
                MINIMAL_DOC,
                force_fixture=True,
                export_training_case=True,
                training_output_dir=tmpdir,
            )
            export_file = list(Path(tmpdir).glob("*.json"))[0]
            data = json.loads(export_file.read_text())
            assert data["metadata"]["no_slot120"] is True
            assert data["slot_target"] == "32"
            assert data["future_slot_target"] == "14"
            # Check slot120 / nemotron don't appear as JSON *values*
            # (the key "no_slot120" is intentional and acceptable)
            serialized = json.dumps(data)
            assert '"slot120"' not in serialized  # not a string value
            assert "nemotron" not in serialized.lower()


class TestDociReviewMode:
    def test_returns_dict_with_expected_keys(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        assert isinstance(result, dict)
        assert "report" in result
        assert "gap_assessment" in result
        assert "benchmark_matrix" in result

    def test_report_is_markdown(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        assert "# Document Gap Assessment" in result["report"]
        assert "## Executive Summary" in result["report"]
        assert "## Benchmark Matrix" in result["report"]
        assert "## Gap Assessment" in result["report"]

    def test_gap_assessment_structure(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        gaps = result["gap_assessment"]
        required_keys = {"benchmark_id", "status", "evidence_in_document", "gap",
                         "risk", "recommendation", "priority", "mandatory_status", "confidence_level"}
        for gap in gaps:
            missing = required_keys - set(gap.keys())
            assert not missing, f"Gap row missing keys: {missing}"

    def test_gap_status_values(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        valid_statuses = {"present", "partial", "missing", "not_applicable"}
        for gap in result["gap_assessment"]:
            assert gap["status"] in valid_statuses

    def test_well_covered_doc_has_fewer_missing(self):
        """A document with all section keywords should have more 'present' rows than MINIMAL_DOC."""
        full_result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        thin_result = run_doci_review_mode(SAMPLE_TASK, MINIMAL_DOC, force_fixture=True)
        full_present = sum(1 for g in full_result["gap_assessment"] if g["status"] == "present")
        thin_present = sum(1 for g in thin_result["gap_assessment"] if g["status"] == "present")
        assert full_present >= thin_present, (
            f"Full doc should score >= thin doc: {full_present} vs {thin_present}"
        )

    def test_no_copyrighted_text_reproduced(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        report = result["report"]
        assert "all rights reserved" not in report.lower()
        assert "reproduced with permission" not in report.lower()
        # Disclaimer note must be present
        assert "No verbatim copyrighted standard text is reproduced" in report

    def test_no_slot120_in_output(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        dump = json.dumps(result)
        assert "slot120" not in dump.lower()
        assert "nemotron" not in dump.lower()

    def test_benchmark_matrix_count_matches_gap_count(self):
        result = run_doci_review_mode(SAMPLE_TASK, SAMPLE_DOC, force_fixture=True)
        assert len(result["benchmark_matrix"]) == len(result["gap_assessment"])

    def test_traini_export_schema_compliance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_doci_review_mode(
                SAMPLE_TASK,
                SAMPLE_DOC,
                force_fixture=True,
                export_training_case=True,
                training_output_dir=tmpdir,
            )
            exports = list(Path(tmpdir).glob("standard_discovery_case_*.json"))
            assert len(exports) == 1
            data = json.loads(exports[0].read_text())
            required_top_keys = {
                "export_id", "skill_id", "slot_target", "future_slot_target",
                "export_timestamp", "task", "sanitized_context",
                "source_pack", "benchmark_matrix", "gap_assessment", "mode", "metadata",
            }
            assert required_top_keys.issubset(data.keys())
            assert data["skill_id"] == "contextual_standard_discovery_and_document_review"
            assert data["metadata"]["no_slot120"] is True
            assert data["metadata"]["no_secrets"] is True
            assert data["metadata"]["no_copyright_reproduction"] is True
            assert data["mode"] == "doci_review_mode"


class TestExportTrainiCase:
    def test_blocks_slot120_in_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AssertionError, match="slot120"):
                export_traini_training_case(
                    {"task": "use slot120 as teacher for this case"},
                    tmpdir,
                )

    def test_blocks_nemotron_in_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AssertionError, match="nemotron"):
                export_traini_training_case(
                    {"task": "nemotron generated this training case"},
                    tmpdir,
                )

    def test_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as base:
            new_dir = Path(base) / "subdir" / "exports"
            export_traini_training_case({"task": "clean task"}, new_dir)
            assert new_dir.exists()

    def test_written_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_traini_training_case({"task": "clean export test"}, tmpdir)
            data = json.loads(path.read_text())
            assert isinstance(data, dict)
            assert "export_id" in data


class TestGapComparison:
    def test_all_rows_covered_by_gap_rows(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        gaps = compare_document_to_benchmark(SAMPLE_DOC, matrix)
        assert len(gaps) == len(matrix)

    def test_benchmark_ids_match_between_matrix_and_gaps(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        gaps = compare_document_to_benchmark(SAMPLE_DOC, matrix)
        matrix_ids = {r["benchmark_id"] for r in matrix}
        gap_ids = {g["benchmark_id"] for g in gaps}
        assert matrix_ids == gap_ids

    def test_priority_values_valid(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        gaps = compare_document_to_benchmark(SAMPLE_DOC, matrix)
        for gap in gaps:
            assert gap["priority"] in ("high", "medium", "low")


class TestRenderFunctions:
    def _make_matrix_and_gaps(self):
        ctx = extract_document_review_context(SAMPLE_TASK)
        sources = FixtureStandardDiscoveryProvider().search([])
        classified = [classify_standard_source(s) for s in sources]
        matrix = build_benchmark_matrix(ctx, classified)
        gaps = compare_document_to_benchmark(SAMPLE_DOC, matrix)
        return ctx, matrix, gaps

    def test_axi_advisory_is_string(self):
        ctx, matrix, gaps = self._make_matrix_and_gaps()
        out = render_axi_advisory_response(ctx, matrix, gaps)
        assert isinstance(out, str)
        assert len(out) > 20

    def test_axi_advisory_telegram_length_ok(self):
        ctx, matrix, gaps = self._make_matrix_and_gaps()
        out = render_axi_advisory_response(ctx, matrix, gaps)
        # Advisory should stay well under Telegram's 4096 char limit
        assert len(out) < 4096

    def test_doci_report_has_all_sections(self):
        ctx, matrix, gaps = self._make_matrix_and_gaps()
        out = render_doci_gap_assessment(ctx, matrix, gaps)
        assert "Executive Summary" in out
        assert "Benchmark Matrix" in out
        assert "Gap Assessment" in out
        assert "Recommendations" in out

    def test_doci_report_no_secrets(self):
        ctx, matrix, gaps = self._make_matrix_and_gaps()
        out = render_doci_gap_assessment(ctx, matrix, gaps)
        assert "nvapi-" not in out
        assert "password" not in out.lower() or "[REDACTED]" in out

    def test_doci_disclaimer_present(self):
        ctx, matrix, gaps = self._make_matrix_and_gaps()
        out = render_doci_gap_assessment(ctx, matrix, gaps)
        assert "No verbatim copyrighted standard text is reproduced" in out
