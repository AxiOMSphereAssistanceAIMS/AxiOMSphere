from ops.agents.poli_change_auditor import evaluate_fullstack_change


def _proposal(**overrides):
    result = {
        "strategy_change": False,
        "concept_preserved": True,
        "restorative": True,
        "production_mutation": False,
        "certified_pipeline_compatibility": True,
        "provenance_complete": True,
        "rollback_plan": ["restore bounded diff"],
        "certified_pipeline_compatibility_evidence": "qa_regression.txt",
        "provenance_complete_evidence": "evidence_manifest.json",
        "rollback_present_evidence": "evidence_manifest.json:rollback",
        "concept_preserved_evidence": "codex_audit.json:findings",
        "restorative_evidence": "codex_audit.json:findings",
        "strategy_preserved_evidence": "codex_audit.json:findings",
        "protected_boundary_clear_evidence": "evidence_manifest.json:changed_files",
        "protected_boundary_mutation": False,
        "evidence_manifest": {"task_id": "test", "qa_exit_code": 0, "artifacts_verified": True},
    }
    result.update(overrides)
    return result


def test_poli_allows_codex_passed_compatible_change(tmp_path):
    manifest = tmp_path / "manifest.json"
    qa = tmp_path / "qa.txt"; qa.write_text("45 passed", encoding="utf-8")
    report = tmp_path / "report.md"; report.write_text("closure", encoding="utf-8")
    baseline = tmp_path / "baseline"; baseline.mkdir()
    source = tmp_path / "source.py"; source.write_text("pass", encoding="utf-8")
    (baseline / "source.py").write_text("pass", encoding="utf-8")
    import hashlib, json
    handoff = tmp_path / "handoff.json"; handoff.write_text('{"implementation_status":"COMPLETED_VERIFIED"}', encoding="utf-8")
    payload = {"task_id":"test", "qa_result":{"exit_code":0,"test_count":45,"artifact":str(qa),"command":["pytest"],"artifact_sha256":hashlib.sha256(qa.read_bytes()).hexdigest()}, "final_report":{"path":str(report),"sha256":hashlib.sha256(report.read_bytes()).hexdigest()}, "rollback":{"operator_confirmation_required":True,"baseline_dir":str(baseline),"restore_command":"restore","baseline_inventory":[{"path":"source.py","sha256":hashlib.sha256(source.read_bytes()).hexdigest()}]}, "reviewed_files":[{"path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}], "expected_reviewed_files":[str(source)], "implementation_handoff":{"path":str(handoff),"sha256":hashlib.sha256(handoff.read_bytes()).hexdigest()}, "constraints":{"production_mutation":False}}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    proposal = _proposal() | {"task_id": "test", "evidence_manifest": {"task_id": "test", "manifest_path": str(manifest)}}
    result = evaluate_fullstack_change(
        proposal,
        {"status": "PASSED", "auditor_available": True, "findings": []},
    )
    assert result["decision"] == "ALLOW"
    assert result["holder"] == "Poli"
    assert result["telegram_action"] == "result_only"


def test_poli_denies_codex_warn_without_telegram_approval():
    result = evaluate_fullstack_change(
        _proposal(),
        {"status": "WARN", "auditor_available": True, "findings": []},
    )
    assert result["decision"] == "DENY"
    assert result["allowed"] is False


def test_poli_denies_strategy_or_certified_pipeline_break():
    result = evaluate_fullstack_change(
        _proposal(strategy_change=True, certified_pipeline_compatibility=False),
        {"status": "PASSED", "auditor_available": True, "findings": []},
    )
    assert result["decision"] == "DENY"
    assert any("strategy" in reason for reason in result["reasons"])
