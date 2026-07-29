import hashlib
import json

import pytest

from ops.agents.poli_checklist import build_checklist_packet


def _write_manifest(tmp_path, *, extra_reviewed_path: str | None = None, extra_changed_path: str | None = None):
    manifest = tmp_path / "manifest.json"
    qa = tmp_path / "qa.txt"; qa.write_text("45 passed", encoding="utf-8")
    report = tmp_path / "report.md"; report.write_text("closure", encoding="utf-8")
    baseline = tmp_path / "baseline"; baseline.mkdir(exist_ok=True)
    source = tmp_path / "source.py"; source.write_text("pass", encoding="utf-8")
    (baseline / "source.py").write_text("pass", encoding="utf-8")
    handoff = tmp_path / "handoff.json"
    handoff.write_text('{"implementation_status":"COMPLETED_VERIFIED"}', encoding="utf-8")
    reviewed_files = [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
    expected_reviewed_files = [str(source)]
    if extra_reviewed_path:
        extra = tmp_path / "extra.py"
        # Point the reviewed-file entry's *logical* path at the protected
        # prefix under test while still resolving a real, hashable file on
        # disk (a real manifest would use a repo-relative path here).
        extra.write_text("pass", encoding="utf-8")
        reviewed_files = [{"path": extra_reviewed_path, "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
                           "_disk_path": str(extra)}]
        expected_reviewed_files = [extra_reviewed_path]
    payload = {
        "task_id": "test",
        "qa_result": {"exit_code": 0, "test_count": 45, "artifact": str(qa), "command": ["pytest"],
                      "artifact_sha256": hashlib.sha256(qa.read_bytes()).hexdigest()},
        "final_report": {"path": str(report), "sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
        "rollback": {"operator_confirmation_required": True, "baseline_dir": str(baseline),
                     "restore_command": "restore",
                     "baseline_inventory": [{"path": "source.py",
                                              "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]},
        "reviewed_files": [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
        "expected_reviewed_files": [str(source)],
        "implementation_handoff": {"path": str(handoff), "sha256": hashlib.sha256(handoff.read_bytes()).hexdigest()},
        "constraints": {"production_mutation": False},
    }
    if extra_changed_path:
        payload["changed_files"] = [{"path": extra_changed_path, "sha256": "irrelevant"}]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def _proposal(manifest_path):
    return {
        "strategy_change": False,
        "concept_preserved": True,
        "restorative": True,
        "certified_pipeline_compatibility": True,
        "provenance_complete": True,
        "rollback_plan": ["restore"],
        "certified_pipeline_compatibility_evidence": "qa_regression.txt",
        "provenance_complete_evidence": "evidence_manifest.json",
        "rollback_present_evidence": "evidence_manifest.json:rollback",
        "concept_preserved_evidence": "codex_audit.json:findings",
        "restorative_evidence": "codex_audit.json:findings",
        "strategy_preserved_evidence": "codex_audit.json:findings",
        "protected_boundary_clear_evidence": "evidence_manifest.json:changed_files",
        "evidence_manifest": {"task_id": "test", "manifest_path": str(manifest_path)},
        "task_id": "test",
        "production_mutation": False,
        "protected_boundary_mutation": False,
    }


_CLEAN_CODEX = {"status": "PASSED", "auditor_available": True, "findings": []}


def test_poli_checklist_allows_complete_codex_reviewed_packet(tmp_path):
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "ALLOW"
    assert len(result["checks"]) == 9
    assert result["telegram_action"] == "result_only_human_summary"


def test_poli_checklist_blocks_missing_certification_evidence(tmp_path):
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    proposal["certified_pipeline_compatibility"] = False
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "DENY"
    assert "certified_pipeline_compatibility" in result["blocked_checks"]


def test_poli_rejects_invented_manifest():
    proposal = _proposal("/missing") | {"evidence_manifest": {"task_id": "wrong", "manifest_path": "/missing"}}
    assert build_checklist_packet(proposal, _CLEAN_CODEX)["decision"] == "DENY"


def test_concept_preserved_is_not_trusted_from_proposal_alone(tmp_path):
    """Regression test for the self-attestation gap: concept_preserved=True
    with no independent corroboration must DENY, not silently pass through
    on the proposer's own say-so."""
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    proposal["concept_preserved"] = True
    # Codex reviewed the real diff and found a BLOCKING problem — the
    # proposer's self-declared "concept_preserved" claim is contradicted by
    # the one independent artifact that could back it.
    codex_with_blocker = {"status": "PASSED", "auditor_available": True,
                           "findings": [{"severity": "BLOCKING", "category": "concept",
                                         "finding": "removes the documented concept boundary"}]}
    result = build_checklist_packet(proposal, codex_with_blocker)
    assert result["decision"] == "DENY"
    assert "concept_preserved" in result["blocked_checks"]


def test_concept_preserved_omitted_defaults_to_deny(tmp_path):
    """The historical bug: proposal.get('concept_preserved', True) silently
    passed any proposal that never mentioned the field at all. Omission must
    now DENY, not ALLOW."""
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    del proposal["concept_preserved"]
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "DENY"
    assert "concept_preserved" in result["blocked_checks"]


def test_rollback_present_requires_real_verified_manifest_not_just_a_string(tmp_path):
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    # A truthy rollback_plan string with a manifest that does NOT verify
    # (points nowhere) must not satisfy rollback_present.
    proposal["evidence_manifest"] = {"task_id": "test", "manifest_path": str(tmp_path / "does_not_exist.json")}
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "DENY"
    assert "rollback_present" in result["blocked_checks"]


def test_protected_boundary_clear_catches_manifest_evidence_proposal_did_not_self_declare(tmp_path):
    """protected_boundary_mutation=False (self-declared) must not be enough
    if the verified manifest shows a changed file under a protected path."""
    manifest = _write_manifest(tmp_path, extra_changed_path="ops/self_healing/policy_gate.py")
    # Point reviewed_files at the same protected path via changed_files so
    # the check is independently derivable from the manifest on disk.
    proposal = _proposal(manifest)
    proposal["protected_boundary_mutation"] = False
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "DENY"
    assert "protected_boundary_clear" in result["blocked_checks"]


def test_evidence_text_required_even_when_all_booleans_true(tmp_path):
    """Every checklist claim now needs a non-empty evidence reference, not
    just a True boolean — closes the 'provenance_complete=true with no
    checkable artifact' pattern for all fields, not only the two that were
    already covered."""
    manifest = _write_manifest(tmp_path)
    proposal = _proposal(manifest)
    del proposal["restorative_evidence"]
    result = build_checklist_packet(proposal, _CLEAN_CODEX)
    assert result["decision"] == "DENY"
    assert "restorative" in result["blocked_checks"]
