from __future__ import annotations

import json
from pathlib import Path

from ops import cyclic_doc_generation_pipeline as pipeline


def _document(count: int) -> str:
    return "\n\n".join(
        f"## {index}.0 Section {index}\nSubstantive content for section {index}."
        for index in range(1, count + 1)
    )


def _audit_payload(section_count: int) -> dict:
    return {
        "section_findings": [
            {
                "section": f"{index}.0 Section {index}",
                "gap_score": 0.7,
                "recommendations": [
                    f"Section {index}.0: Add control requirement {index}"
                ],
                "missing_standards": [],
            }
            for index in range(1, section_count + 1)
        ],
        "missing_sections": [],
        "omi_quality": {
            "standards_accuracy": 0.6,
            "completeness": 0.7,
            "context_relevance": 0.8,
        },
        "axi_quality": {
            "standards_accuracy": 0.7,
            "completeness": 0.8,
            "context_relevance": 0.9,
        },
        "overall_assessment": "Bounded audit completed.",
        "skill_recommendations": ["Improve section targeting."],
    }


def _write_evidence_files(evidence_dir, prompt: str, payload: dict) -> None:
    """Write the same evidence files bedrock_doc_audit() would write."""
    ed = Path(evidence_dir)
    ed.mkdir(parents=True, exist_ok=True)
    (ed / "claude_audit_prompt.txt").write_text(prompt, encoding="utf-8")
    (ed / "claude_audit_raw_stdout.json").write_text(
        json.dumps({"raw_text": json.dumps(payload), "model_id": "us.anthropic.claude-sonnet-4-6"}),
        encoding="utf-8",
    )
    (ed / "claude_audit_parsed.json").write_text(
        json.dumps({"parsed": payload, "audit_provider": "aws_bedrock_direct", "degraded_audit_mode": False}),
        encoding="utf-8",
    )


def test_claude_audit_uses_one_full_document_call(monkeypatch, tmp_path) -> None:
    calls = []
    payload = _audit_payload(5)

    def fake_bedrock_doc_audit(prompt, model_alias="opus", max_tokens=8000, timeout=600, evidence_dir=None):
        calls.append({"prompt": prompt, "evidence_dir": evidence_dir})
        if evidence_dir is not None:
            _write_evidence_files(evidence_dir, prompt, payload)
        return payload

    monkeypatch.setattr(pipeline, "bedrock_doc_audit", fake_bedrock_doc_audit)
    result = pipeline._claude_code_audit(
        omi_standards=[],
        axi_standards=[],
        doc_excerpt=_document(5),
        axi_recommendations=[],
        topic="AIM",
        reference_text="Full reference text.",
        cycle=1,
        structure_report={"completeness_ratio": 0.9},
        evidence_dir=tmp_path,
    )

    assert result is not None
    assert len(calls) == 1
    assert "Full reference text." in calls[0]["prompt"]
    assert result.reference_gap["sections_audited"] == 5
    assert result.reference_gap["audit_mode"] == "single_pass_full_document"
    assert (tmp_path / "claude_audit_prompt.txt").is_file()
    assert (tmp_path / "claude_audit_raw_stdout.json").is_file()
    assert (tmp_path / "claude_audit_parsed.json").is_file()


def test_claude_audit_rejects_under_80_percent_coverage(
    monkeypatch,
    tmp_path,
) -> None:
    payload = _audit_payload(3)

    def fake_bedrock_doc_audit(prompt, model_alias="opus", max_tokens=8000, timeout=600, evidence_dir=None):
        if evidence_dir is not None:
            _write_evidence_files(evidence_dir, prompt, payload)
        return payload

    monkeypatch.setattr(pipeline, "bedrock_doc_audit", fake_bedrock_doc_audit)
    result = pipeline._claude_code_audit(
        omi_standards=[],
        axi_standards=[],
        doc_excerpt=_document(5),
        axi_recommendations=[],
        topic="AIM",
        reference_text="Full reference text.",
        evidence_dir=tmp_path,
    )

    # Bedrock was invoked and returned data, but coverage was insufficient (3/5 sections).
    # The pipeline preserves bedrock_invoked=True in a degraded result rather than
    # discarding the call entirely — so result is not None but is marked degraded.
    assert result is not None
    assert result.bedrock_invoked is True
    assert "coverage" in result.overall_assessment.lower()


def test_claude_audit_filters_missing_sections_present_in_document(
    monkeypatch,
    tmp_path,
) -> None:
    payload = _audit_payload(2)
    payload["missing_sections"] = [
        "1. Section 1 [MISSING FROM BODY]",
        "3. Truly Missing Section",
    ]

    def fake_bedrock_doc_audit(
        prompt,
        model_alias="opus",
        max_tokens=8000,
        timeout=600,
        evidence_dir=None,
    ):
        if evidence_dir is not None:
            _write_evidence_files(evidence_dir, prompt, payload)
        return payload

    monkeypatch.setattr(
        pipeline,
        "bedrock_doc_audit",
        fake_bedrock_doc_audit,
    )
    result = pipeline._claude_code_audit(
        omi_standards=[],
        axi_standards=[],
        doc_excerpt=_document(2),
        axi_recommendations=[],
        topic="AIM",
        reference_text="Full reference text.",
        evidence_dir=tmp_path,
    )

    assert result is not None
    assert result.reference_gap["missing_sections"] == [
        "3. Truly Missing Section"
    ]


def test_grounded_repair_bridge_accepts_only_exact_reference_quotes(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "recommendations": [
            {
                "section": "2.0 Scope",
                "text": "Add the pump boundary and excluded equipment.",
                "evidence_quote": "The scope includes centrifugal pumps and excludes turbines.",
            },
            {
                "section": "3.0 Roles",
                "text": "Invent a role.",
                "evidence_quote": "This quote is not in the reference.",
            },
            {
                "section": "2.0 Scope",
                "text": "Add an ISO 99999 control.",
                "evidence_quote": "The scope includes centrifugal pumps and excludes turbines.",
            },
            {
                "section": "2.0 Scope",
                "text": "Apply API 610 pump requirements.",
                "evidence_source": "API 610 — Centrifugal Pumps",
                "evidence_quote": "Requirements for centrifugal pump design and operation.",
            },
        ]
    }

    monkeypatch.setattr(
        pipeline,
        "bedrock_doc_audit",
        lambda **_kwargs: payload,
    )
    result = pipeline._grounded_repair_bridge(
        doc_text="## 2.0 Scope\nCurrent scope.\n\n## 3.0 Roles\nCurrent roles.",
        reference_text=(
            "The scope includes centrifugal pumps and excludes turbines."
        ),
        generated_sections=["2.0 Scope", "3.0 Roles"],
        audit_result=pipeline.ClaudeAuditResult(
            omi_quality={
                "standards_accuracy": 0.8,
                "completeness": 0.8,
                "context_relevance": 0.8,
            },
            axi_quality={
                "standards_accuracy": 0.8,
                "completeness": 0.8,
                "context_relevance": 0.8,
            },
            overall_assessment="Scope is incomplete.",
            missing_standards=[],
            audit_time=1.0,
            skill_recommendations=["Improve scope specificity."],
        ),
        audit_quality_failures=["claude_axi_quality=80% < 85%"],
        evidence_dir=tmp_path,
        contextual_sources=[
            {
                "source_title": "API 610 — Centrifugal Pumps",
                "excerpt": (
                    "Requirements for centrifugal pump design and operation."
                ),
            }
        ],
    )

    assert result == [
        "Section 2.0 Scope: Add the pump boundary and excluded equipment.",
        "Section 2.0 Scope: Apply API 610 pump requirements.",
    ]
    evidence = json.loads(
        (
            tmp_path
            / "grounded_repair_bridge"
            / "grounded_repair_result.json"
        ).read_text()
    )
    assert evidence["status"] == "GROUNDED_REPAIRS_CREATED"
    assert {
        item["reason"] for item in evidence["rejected"]
    } == {
        "evidence_quote_not_in_bound_sources",
        "unsupported_standard_citations",
    }
