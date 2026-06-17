import json
import importlib
import subprocess
from dataclasses import replace

import pytest

from ops.agents.skills.context_grounded_document_generation import (
    CapsuleCoverageError,
    ContextSource,
    GenerationContext,
    SectionPlanError,
    ShardCoverageError,
    build_grounded_catalog_bundle,
    build_requirement_catalog,
    build_section_contract,
    build_section_plan,
    build_generation_context,
    generate_document_from_catalog,
    parse_requirement_capsule_batch,
    render_capsule_extraction_prompt,
    require_complete_shard_coverage,
    require_complete_capsule_coverage,
    require_complete_section_plan,
    render_generation_prompt,
    render_section_generation_prompt,
    semantic_split,
    validate_capsule_coverage,
    validate_shard_coverage,
)
from ops import cyclic_doc_generation_pipeline as pipeline


def test_context_builder_does_not_truncate_reference_or_task_context() -> None:
    reference = "REFERENCE_START\n" + ("reference-body\n" * 10000) + "REFERENCE_END"
    task = "TASK_START\n" + ("task-body\n" * 3000) + "TASK_END"

    context = build_generation_context(
        topic="Asset Integrity Management Policy and Framework",
        doc_type="policy",
        task_context=task,
        standards=["ISO 55001"],
        reference_text=reference,
        reference_path="reference.pdf",
        similar_limit=0,
    )
    prompt = render_generation_prompt(context)

    assert "REFERENCE_START" in prompt
    assert "REFERENCE_END" in prompt
    assert "TASK_START" in prompt
    assert "TASK_END" in prompt
    section_template = next(
        item
        for item in context.templates
        if item.title == "section_templates.yaml"
    )
    assert "AIMS Elements" in section_template.content
    assert "PROCEDURE" not in section_template.content
    assert "INSPECTION_REPORT" not in section_template.content


@pytest.mark.parametrize(
    ("doc_type", "expected_template", "forbidden_template"),
    [
        ("maintenance_procedure", "procedure.yaml", "policy.yaml"),
        ("policy_framework", "policy.yaml", "procedure.yaml"),
    ],
)
def test_context_builder_binds_document_type_template_without_cross_type_fallback(
    doc_type: str,
    expected_template: str,
    forbidden_template: str,
) -> None:
    context = build_generation_context(
        topic="Centrifugal pump maintenance",
        doc_type=doc_type,
        task_context="governed task",
        similar_limit=0,
    )

    template_names = {item.title for item in context.templates}
    assert expected_template in template_names
    assert forbidden_template not in template_names
    prompt = render_generation_prompt(context)
    assert f"document type MUST remain exactly: {doc_type}" in prompt
    assert "Do not relabel the output as a technical_report" in prompt


def test_render_includes_full_similar_document_content() -> None:
    tail = "SIMILAR_DOCUMENT_END"
    context = GenerationContext(
        topic="Policy",
        doc_type="policy",
        task_context="context",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[
            ContextSource(
                source_type="similar_document",
                title="similar",
                content=("x" * 30000) + tail,
            )
        ],
        provenance=[],
        warnings=[],
    )

    assert tail in render_generation_prompt(context)


def test_slot120_sends_full_prompt_without_character_truncation(
    monkeypatch,
) -> None:
    tail = "FULL_PROMPT_END"
    prompt = ("x" * 200000) + tail
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return _StreamResponse(
            [
                b'{"response":"' + (b"ok" * 100) + b'","done":false}\n',
                b'{"response":"","done":true,"done_reason":"stop",'
                b'"prompt_eval_count":50000}\n',
            ]
        )

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    result = pipeline._slot120_generate(prompt, num_predict=20)
    assert result == "ok" * 100
    assert tail in captured["body"]["prompt"]
    assert captured["body"]["options"]["num_ctx"] == 32768


class _StreamResponse:
    def __init__(self, lines: list[bytes]):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self.lines)


def test_slot120_runtime_matches_current_ollama_profile() -> None:
    assert pipeline.SLOT120_NUM_CTX == 32768
    assert pipeline.OMI_GENERATE_TIMEOUT == 180
    assert pipeline.OMI_GENERATE_NUM_PREDICT == 5000


def test_omi_generation_runtime_limits_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("AIMS_DOC_OMI_GENERATE_TIMEOUT", "420")
    monkeypatch.setenv("AIMS_DOC_OMI_GENERATE_NUM_PREDICT", "3200")
    reloaded = importlib.reload(pipeline)
    try:
        assert reloaded.OMI_GENERATE_TIMEOUT == 420
        assert reloaded.OMI_GENERATE_NUM_PREDICT == 3200
        assert reloaded.IMPROVEMENT_GENERATE_TIMEOUT == 420
        assert reloaded.IMPROVEMENT_GENERATE_NUM_PREDICT == 3200
    finally:
        monkeypatch.delenv("AIMS_DOC_OMI_GENERATE_TIMEOUT", raising=False)
        monkeypatch.delenv("AIMS_DOC_OMI_GENERATE_NUM_PREDICT", raising=False)
        importlib.reload(pipeline)


def test_runtime_preflight_does_not_double_count_loaded_required_model(
    monkeypatch,
    tmp_path,
) -> None:
    ollama_list = subprocess.CompletedProcess(
        args=["ollama", "list"],
        returncode=0,
        stdout=(
            "NAME ID SIZE MODIFIED\n"
            "qwen25-chat-14-v19-new:latest abc 16 GB now\n"
            "qwen36-reasoning-35b-v1:latest def 39 GB now\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: ollama_list,
    )

    class RuntimeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "models": [
                        {
                            "name": "qwen36-reasoning-35b-v1:latest",
                            "size_vram": 39 * 1024**3,
                        },
                        {
                            "name": "unrelated-model:latest",
                            "size_vram": 37 * 1024**3,
                        },
                    ]
                }
            ).encode()

    monkeypatch.setattr(
        pipeline.urllib.request,
        "urlopen",
        lambda *args, **kwargs: RuntimeResponse(),
    )

    result = pipeline._runtime_preflight(tmp_path)

    assert result["status"] == "PASS"
    assert result["projected_vram_fraction"] == pytest.approx(
        92 / 128,
        abs=1e-5,
    )


def test_semantic_split_preserves_every_character_and_hash() -> None:
    source = (
        "# Policy\n\n"
        + ("Paragraph alpha contains governed text.\n\n" * 2500)
        + "## Final Section\n\nFINAL_SOURCE_CHARACTER"
    )

    plan = semantic_split(
        source,
        source_id="reference-aim-pfm",
        max_chars=12000,
    )
    report = require_complete_shard_coverage(plan)

    assert report.passed
    assert plan.reassemble() == source
    assert report.covered_chars == len(source)
    assert all(len(shard.content) <= 12000 for shard in plan.shards)
    assert [shard.start_char for shard in plan.shards[1:]] == [
        shard.end_char for shard in plan.shards[:-1]
    ]
    assert plan.shards[-1].content.endswith("FINAL_SOURCE_CHARACTER")


def test_semantic_split_uses_hard_boundary_without_data_loss() -> None:
    source = "x" * 25001

    plan = semantic_split(source, source_id="unbroken", max_chars=10000)

    assert [len(shard.content) for shard in plan.shards] == [10000, 10000, 5001]
    assert [shard.boundary for shard in plan.shards] == [
        "hard_limit",
        "hard_limit",
        "source_end",
    ]
    assert plan.reassemble() == source


def test_coverage_gate_blocks_missing_shard() -> None:
    plan = semantic_split(
        "section\n\n" * 5000,
        source_id="missing-check",
        max_chars=8000,
    )
    incomplete = plan.shards[:-1]

    report = validate_shard_coverage(plan, incomplete)

    assert not report.passed
    assert report.status == "BLOCKED"
    assert report.missing_shard_ids == (plan.shards[-1].shard_id,)
    with pytest.raises(ShardCoverageError):
        require_complete_shard_coverage(plan, incomplete)


def test_coverage_gate_blocks_tampered_or_reordered_shards() -> None:
    plan = semantic_split(
        "A section.\n\n" * 4000,
        source_id="integrity-check",
        max_chars=7000,
    )
    tampered = list(plan.shards)
    tampered[0] = replace(tampered[0], content=tampered[0].content + "changed")
    tampered_report = validate_shard_coverage(plan, tampered)
    reordered_report = validate_shard_coverage(
        plan,
        [plan.shards[1], plan.shards[0], *plan.shards[2:]],
    )

    assert not tampered_report.passed
    assert any("content_hash_mismatch" in error for error in tampered_report.errors)
    assert not reordered_report.passed
    assert "shard_order_or_count_mismatch" in reordered_report.errors


def _capsule_payload(
    shard,
    *,
    statement: str,
    evidence: str,
    kind: str = "content",
    mandatory: bool = True,
    section_hint: str = "1.0 Introduction",
) -> dict:
    return {
        "source_shard_id": shard.shard_id,
        "source_shard_sha256": shard.sha256,
        "status": "PASS",
        "requirements": [
            {
                "kind": kind,
                "statement": statement,
                "evidence_quote": evidence,
                "mandatory": mandatory,
                "target_section_hint": section_hint,
                "confidence": 0.9,
            }
        ],
        "no_requirements_reason": "",
    }


def test_capsule_parser_requires_verbatim_evidence_and_forces_similar_optional() -> None:
    plan = semantic_split(
        "Purpose: establish an asset integrity framework.",
        source_id="similar-1",
        max_chars=1000,
    )
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement="Establish an asset integrity framework.",
        evidence="establish an asset integrity framework",
        mandatory=True,
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="similar_document",
    )

    assert batch.capsules[0].mandatory is False
    assert batch.capsules[0].category == "similar_pattern"
    payload["requirements"][0]["evidence_quote"] = "invented evidence"
    with pytest.raises(ValueError, match="not present"):
        parse_requirement_capsule_batch(
            shard,
            payload,
            source_type="similar_document",
        )


def test_capsule_parser_canonicalizes_only_unique_whitespace_difference() -> None:
    plan = semantic_split(
        "Requirement applies with\nin this manual.",
        source_id="reference-whitespace",
        max_chars=1000,
    )
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement="Requirement applies within this manual.",
        evidence="Requirement applies with in this manual.",
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="reference",
    )

    capsule = batch.capsules[0]
    assert capsule.evidence_quote == "Requirement applies with\nin this manual."
    assert shard.content[
        capsule.evidence_start:capsule.evidence_end
    ] == capsule.evidence_quote

    ambiguous_plan = semantic_split(
        "same\ntext and same\ntext",
        source_id="ambiguous",
        max_chars=1000,
    )
    ambiguous_shard = ambiguous_plan.shards[0]
    ambiguous_payload = _capsule_payload(
        ambiguous_shard,
        statement="Repeated evidence.",
        evidence="same text",
    )
    with pytest.raises(ValueError, match="ambiguous"):
        parse_requirement_capsule_batch(
            ambiguous_shard,
            ambiguous_payload,
            source_type="reference",
        )


def test_capsule_parser_resolves_unique_bounded_ellipsis_to_exact_source() -> None:
    source = (
        "Asset An asset has potential value. The value varies by stakeholder. "
        "This shall cover operated facilities."
    )
    plan = semantic_split(source, source_id="ellipsis", max_chars=1000)
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement="An asset has value and covers operated facilities.",
        evidence=(
            "Asset An asset has potential value. ... "
            "This shall cover operated facilities."
        ),
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="reference",
    )

    assert batch.capsules[0].evidence_quote == source

    ambiguous_source = f"{source} Duplicate. {source}"
    ambiguous_plan = semantic_split(
        ambiguous_source,
        source_id="ellipsis-ambiguous",
        max_chars=2000,
    )
    ambiguous_payload = _capsule_payload(
        ambiguous_plan.shards[0],
        statement="Ambiguous requirement.",
        evidence=(
            "Asset An asset has potential value. ... "
            "This shall cover operated facilities."
        ),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        parse_requirement_capsule_batch(
            ambiguous_plan.shards[0],
            ambiguous_payload,
            source_type="reference",
        )


def test_capsule_parser_uses_long_unique_exact_fragment_for_pdf_table_order() -> None:
    source = (
        "Asset Integrity Asset Integrity Management System (AIMS) addresses "
        "the Management System assets and the strategies required to assure "
        "the integrity of the physical assets during the operation phase."
    )
    plan = semantic_split(source, source_id="table-order", max_chars=1000)
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement="AIMS assures physical asset integrity during operation.",
        evidence=(
            "Asset Integrity Management System (AIMS) addresses the assets "
            "and the strategies required to assure the integrity of the "
            "physical assets during the operation phase."
        ),
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="reference",
    )

    assert batch.capsules[0].evidence_quote == (
        "assets and the strategies required to assure the integrity of the "
        "physical assets during the operation phase."
    )


def test_reference_capsule_can_use_unique_exact_standard_identifier() -> None:
    source = (
        "Asset management - Management systems - Requirements\n"
        "55001:2014"
    )
    plan = semantic_split(source, source_id="standard-table", max_chars=1000)
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement=(
            "The document references ISO 55001:2014 Asset management "
            "requirements."
        ),
        evidence=(
            "ISO 55001:2014 Asset management - Management systems - "
            "Requirements"
        ),
        kind="reference",
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="reference",
    )

    assert batch.capsules[0].evidence_quote == "55001:2014"


def test_reference_capsule_evidence_must_match_statement_identifier() -> None:
    source = (
        "55002:2018 application of ISO 55001. "
        "ISO 55001 defines management system requirements."
    )
    plan = semantic_split(source, source_id="reference-identity", max_chars=1000)
    shard = plan.shards[0]
    payload = _capsule_payload(
        shard,
        statement="The document references ISO 55002:2018.",
        evidence="application of ISO 55001",
        kind="reference",
    )

    batch = parse_requirement_capsule_batch(
        shard,
        payload,
        source_type="reference",
    )

    assert batch.capsules[0].evidence_quote == "55002:2018"


def test_capsule_coverage_blocks_missing_batch() -> None:
    plan = semantic_split(
        ("Section requirement.\n\n" * 2000),
        source_id="reference",
        max_chars=5000,
    )
    batches = [
        parse_requirement_capsule_batch(
            shard,
            _capsule_payload(
                shard,
                statement=f"Requirement from {shard.shard_id}",
                evidence="Section requirement.",
            ),
            source_type="reference",
        )
        for shard in plan.shards[:-1]
    ]

    report = validate_capsule_coverage(plan, batches)

    assert not report.passed
    assert report.missing_shard_ids == (plan.shards[-1].shard_id,)
    with pytest.raises(CapsuleCoverageError):
        require_complete_capsule_coverage(plan, batches)


def test_catalog_deduplicates_with_provenance_but_separates_categories() -> None:
    reference_plan = semantic_split(
        "The policy shall define its scope.",
        source_id="reference",
        max_chars=1000,
    )
    standard_plan = semantic_split(
        "The policy shall define its scope.",
        source_id="standard",
        max_chars=1000,
    )
    reference_shard = reference_plan.shards[0]
    standard_shard = standard_plan.shards[0]
    reference_batch = parse_requirement_capsule_batch(
        reference_shard,
        _capsule_payload(
            reference_shard,
            statement="The policy shall define its scope.",
            evidence="The policy shall define its scope.",
            section_hint="3.0 Scope",
        ),
        source_type="reference",
    )
    duplicate_reference_batch = parse_requirement_capsule_batch(
        reference_shard,
        {
            **_capsule_payload(
                reference_shard,
                statement="The policy shall define its scope.",
                evidence="The policy shall define its scope.",
                section_hint="Scope",
            ),
            "requirements": [
                _capsule_payload(
                    reference_shard,
                    statement="The policy shall define its scope.",
                    evidence="The policy shall define its scope.",
                    section_hint="Scope",
                )["requirements"][0],
                {
                    "kind": "content",
                    "statement": "The policy shall define its scope.",
                    "evidence_quote": "The policy shall define its scope.",
                    "mandatory": True,
                    "target_section_hint": "3.0 Scope",
                    "confidence": 0.8,
                },
            ],
        },
        source_type="reference",
    )
    standard_batch = parse_requirement_capsule_batch(
        standard_shard,
        _capsule_payload(
            standard_shard,
            statement="The policy shall define its scope.",
            evidence="The policy shall define its scope.",
            section_hint="3.0 Scope",
        ),
        source_type="standard",
    )

    catalog = build_requirement_catalog(
        [
            (reference_plan, [duplicate_reference_batch]),
            (standard_plan, [standard_batch]),
        ],
        catalog_id="test-catalog",
    )

    assert len(catalog.requirements) == 2
    reference_requirement = next(
        item
        for item in catalog.requirements
        if item.category == "reference_requirement"
    )
    assert len(reference_requirement.provenance) == 2
    assert dict(catalog.category_counts) == {
        "reference_requirement": 1,
        "standard_requirement": 1,
    }
    assert reference_batch.capsules[0].statement == (
        reference_requirement.statement
    )


def test_section_plan_assigns_mandatory_requirements_or_blocks() -> None:
    context = GenerationContext(
        topic="Asset Integrity Management Policy and Framework",
        doc_type="policy",
        task_context="",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )
    source = (
        "The document shall define its scope. "
        "The document shall define acronyms."
    )
    plan = semantic_split(source, source_id="reference", max_chars=1000)
    shard = plan.shards[0]
    batch = parse_requirement_capsule_batch(
        shard,
        {
            "source_shard_id": shard.shard_id,
            "source_shard_sha256": shard.sha256,
            "status": "PASS",
            "requirements": [
                {
                    "kind": "content",
                    "statement": "Define document scope.",
                    "evidence_quote": "define its scope",
                    "mandatory": True,
                    "target_section_hint": "3.0 Scope",
                    "confidence": 1.0,
                },
                {
                    "kind": "definition",
                    "statement": "Define governed acronyms.",
                    "evidence_quote": "define acronyms",
                    "mandatory": True,
                    "target_section_hint": "5.0 Definitions and Acronyms",
                    "confidence": 1.0,
                },
            ],
            "no_requirements_reason": "",
        },
        source_type="reference",
    )
    catalog = build_requirement_catalog(
        [(plan, [batch])],
        catalog_id="section-plan",
    )
    sections = build_section_contract(context)

    section_plan = require_complete_section_plan(catalog, sections)
    prompt = render_section_generation_prompt(
        catalog=catalog,
        plan=section_plan,
        section_id="3.0",
    )

    assert section_plan.passed
    assert not section_plan.unassigned_mandatory_requirement_ids
    assert catalog.catalog_sha256 in prompt
    assert "Define document scope." in prompt

    broken_catalog = replace(
        catalog,
        requirements=(
            replace(
                catalog.requirements[0],
                statement="Unmappable mandatory requirement xyzzy.",
                target_section_hints=(),
                kind="constraint",
            ),
        ),
    )
    blocked = build_section_plan(broken_catalog, sections)
    assert not blocked.passed
    with pytest.raises(SectionPlanError):
        require_complete_section_plan(broken_catalog, sections)


def test_section_plan_routes_hierarchical_and_template_alias_hints() -> None:
    context = GenerationContext(
        topic="Asset Integrity Management Policy and Framework",
        doc_type="policy",
        task_context="",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )
    source = (
        "Contractors shall meet integrity requirements. "
        "The revision history shall include a version."
    )
    shard_plan = semantic_split(source, source_id="routing", max_chars=1000)
    shard = shard_plan.shards[0]
    batch = parse_requirement_capsule_batch(
        shard,
        {
            "source_shard_id": shard.shard_id,
            "source_shard_sha256": shard.sha256,
            "status": "PASS",
            "requirements": [
                {
                    "kind": "constraint",
                    "statement": "Contractors shall meet integrity requirements.",
                    "evidence_quote": (
                        "Contractors shall meet integrity requirements."
                    ),
                    "mandatory": True,
                    "target_section_hint": (
                        "8.18 Element 18: Supplier and Contractor Management"
                    ),
                    "confidence": 1.0,
                },
                {
                    "kind": "structure",
                    "statement": "Revision history shall include a version.",
                    "evidence_quote": (
                        "The revision history shall include a version."
                    ),
                    "mandatory": True,
                    "target_section_hint": "revision_history",
                    "confidence": 1.0,
                },
            ],
            "no_requirements_reason": "",
        },
        source_type="reference",
    )
    catalog = build_requirement_catalog(
        [(shard_plan, [batch])],
        catalog_id="routing",
    )

    plan = require_complete_section_plan(
        catalog,
        build_section_contract(context),
    )
    assignments = {
        item.section_id: item.requirement_ids
        for item in plan.assignments
    }
    by_statement = {
        item.statement: item.requirement_id
        for item in catalog.requirements
    }

    assert (
        by_statement["Contractors shall meet integrity requirements."]
        in assignments["8.18"]
    )
    assert (
        by_statement["Revision history shall include a version."]
        in assignments["0.1"]
    )


def test_capsule_prompt_contains_full_shard_and_strict_identity() -> None:
    tail = "CAPSULE_SHARD_END"
    plan = semantic_split(
        ("x" * 20000) + tail,
        source_id="large-reference",
        max_chars=25000,
    )
    shard = plan.shards[0]

    prompt = render_capsule_extraction_prompt(
        shard,
        source_type="reference",
        source_title="Reference",
    )

    assert tail in prompt
    assert shard.shard_id in prompt
    assert shard.sha256 in prompt
    assert "strict JSON only" in prompt


def test_candidate_bundle_builds_and_generates_sections_deterministically() -> None:
    context = GenerationContext(
        topic="Asset Integrity Management Policy and Framework",
        doc_type="policy",
        task_context="The policy shall define its purpose.",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )

    def extractor(shard, source_type, source_title):
        assert source_type == "task"
        assert source_title.endswith("task context")
        return _capsule_payload(
            shard,
            statement="Define the policy purpose.",
            evidence="define its purpose",
            section_hint="2.0 Purpose and Objective",
        )

    bundle = build_grounded_catalog_bundle(
        context,
        extractor=extractor,
        max_shard_chars=1000,
        catalog_id="candidate-test",
    )
    generated = generate_document_from_catalog(
        bundle,
        generator=lambda prompt, section: (
            f"Controlled body for {section.section_id}. "
            f"Catalog visible: {bundle.catalog.catalog_sha256 in prompt}."
        ),
    )

    assert bundle.section_plan.passed
    assert len(bundle.catalog.requirements) == 1
    assert len(generated.sections) == len(bundle.section_plan.sections)
    assert generated.catalog_sha256 == bundle.catalog.catalog_sha256
    assert generated.markdown.startswith(
        "## 0.1 Document Control and Revision History"
    )
    assert "## 1.0 Introduction" in generated.markdown
    assert "## 2.0 Purpose and Objective" in generated.markdown
    assert all(
        section.body_sha256 and section.prompt_sha256
        for section in generated.sections
    )


def test_candidate_generation_rejects_model_heading_changes() -> None:
    context = GenerationContext(
        topic="Policy",
        doc_type="policy",
        task_context="The policy shall define its purpose.",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )

    def extractor(shard, source_type, source_title):
        return _capsule_payload(
            shard,
            statement="Define the policy purpose.",
            evidence="define its purpose",
            section_hint="purpose",
        )

    bundle = build_grounded_catalog_bundle(
        context,
        extractor=extractor,
        max_shard_chars=1000,
    )

    with pytest.raises(ValueError, match="heading boundary"):
        generate_document_from_catalog(
            bundle,
            generator=lambda prompt, section: "## 9.9 Changed Boundary\nBody",
        )


def test_candidate_generation_strips_only_exact_duplicate_heading() -> None:
    context = GenerationContext(
        topic="Policy",
        doc_type="policy",
        task_context="The policy shall define its purpose.",
        standards=[],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )

    def extractor(shard, source_type, source_title):
        return _capsule_payload(
            shard,
            statement="Define the policy purpose.",
            evidence="define its purpose",
            section_hint="purpose",
        )

    bundle = build_grounded_catalog_bundle(
        context,
        extractor=extractor,
        max_shard_chars=1000,
    )
    generated = generate_document_from_catalog(
        bundle,
        generator=lambda prompt, section: f"# {section.title}\nControlled body.",
    )

    assert generated.sections[0].body == "Controlled body."
    first_title = bundle.section_plan.sections[0].title
    assert generated.markdown.count(first_title) == 1


def test_mandatory_standard_gets_deterministic_reference_capsule() -> None:
    context = GenerationContext(
        topic="Asset Integrity Management Policy and Framework",
        doc_type="policy",
        task_context="",
        standards=["ISO 55001:2024"],
        reference=None,
        templates=[],
        similar_documents=[],
        provenance=[],
        warnings=[],
    )

    def extractor(*args):
        raise AssertionError("mandatory standards must not require model extraction")

    bundle = build_grounded_catalog_bundle(
        context,
        extractor=extractor,
        max_shard_chars=1000,
    )

    requirement = bundle.catalog.requirements[0]
    assignment = next(
        item
        for item in bundle.section_plan.assignments
        if item.section_id == "6.2"
    )
    assert requirement.category == "standard_requirement"
    assert requirement.mandatory
    assert "ISO 55001:2024" in requirement.statement
    assert requirement.requirement_id in assignment.requirement_ids
