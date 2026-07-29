from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ops.logi.closed_loop import (
    AUDIT_SCHEMA,
    AUDIT_SCOPE,
    _bindings_probe,
    _codex_audit_probe,
    _ledger_inventory,
    run_closed_loop,
    _traini_gate_probe,
)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_malformed_ledger_is_a_blocker(tmp_path: Path) -> None:
    ledger = tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    _write(ledger, "{bad json}\n")
    rows, errors = _ledger_inventory(tmp_path)
    assert rows == []
    assert errors


def test_inspect_with_invalid_ledger_writes_no_benefit_probes(tmp_path: Path) -> None:
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    ledger = tmp_path / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    _write(ledger, "{bad json}\n")
    report = run_closed_loop(tmp_path, apply_benefit=False)
    assert report["ledger_gate"]["status"] == "BLOCKED"
    assert not (tmp_path / "aims_workspace/logi/benefit_probes").exists()


def _write_real_looking_transcript(tmp_path: Path) -> Path:
    transcript = tmp_path / "codex_cli_audit_raw.txt"
    transcript.write_text(
        "session_id: codex-cli-test-session\n" + ("codex tool_use turn line\n" * 200),
        encoding="utf-8",
    )
    return transcript


def _codex_audit_payload(tmp_path: Path, transcript: Path) -> dict:
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in AUDIT_SCOPE}
    return {
        "schema": AUDIT_SCHEMA,
        "auditor_tool": "OpenAI Codex CLI",
        "verdict": "PASS",
        "blocking_findings": [],
        "non_blocking_findings": [],
        "invariants": {"all_required_invariants": True},
        "certification_recommendation": "READY_FOR_24H_CERTIFICATION",
        "tests": {"passed": 1},
        "summary": "clean",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": list(AUDIT_SCOPE),
        "audited_files_sha256": hashes,
        "raw_transcript": {
            "path": str(transcript),
            "sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
        },
    }


def test_codex_audit_requires_fresh_scope_bound_hashes(tmp_path: Path) -> None:
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    transcript = _write_real_looking_transcript(tmp_path)
    evidence = tmp_path / "audit.json"
    evidence.write_text(json.dumps(_codex_audit_payload(tmp_path, transcript)), encoding="utf-8")
    assert _codex_audit_probe(tmp_path, evidence)["status"] == "PASS"
    data = json.loads(evidence.read_text())
    data["generated_at_utc"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    evidence.write_text(json.dumps(data), encoding="utf-8")
    assert _codex_audit_probe(tmp_path, evidence)["status"] == "BLOCKED"
    data["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    data.pop("invariants")
    evidence.write_text(json.dumps(data), encoding="utf-8")
    assert _codex_audit_probe(tmp_path, evidence)["status"] == "BLOCKED"


def test_codex_audit_rejects_json_only_evidence_with_no_raw_transcript(tmp_path: Path) -> None:
    """A hand-authored JSON matching the schema, with no corroborating Codex
    CLI transcript, must not read as a genuine independent audit."""
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    transcript = _write_real_looking_transcript(tmp_path)
    payload = _codex_audit_payload(tmp_path, transcript)
    del payload["raw_transcript"]
    evidence = tmp_path / "audit.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = _codex_audit_probe(tmp_path, evidence)
    assert result["status"] == "BLOCKED"
    assert any("raw Codex CLI transcript" in reason for reason in result["reasons"])


def test_codex_audit_rejects_missing_transcript_file(tmp_path: Path) -> None:
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    transcript = _write_real_looking_transcript(tmp_path)
    payload = _codex_audit_payload(tmp_path, transcript)
    transcript.unlink()
    evidence = tmp_path / "audit.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = _codex_audit_probe(tmp_path, evidence)
    assert result["status"] == "BLOCKED"
    assert any("transcript file does not exist" in reason for reason in result["reasons"])


def test_codex_audit_rejects_implausibly_small_transcript(tmp_path: Path) -> None:
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    transcript = tmp_path / "tiny.txt"
    transcript.write_text("PASS", encoding="utf-8")
    payload = _codex_audit_payload(tmp_path, transcript)
    evidence = tmp_path / "audit.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = _codex_audit_probe(tmp_path, evidence)
    assert result["status"] == "BLOCKED"
    assert any("implausibly small" in reason for reason in result["reasons"])


def test_codex_audit_rejects_tampered_transcript_hash(tmp_path: Path) -> None:
    for name in AUDIT_SCOPE:
        _write(tmp_path / name, name)
    transcript = _write_real_looking_transcript(tmp_path)
    payload = _codex_audit_payload(tmp_path, transcript)
    transcript.write_text(transcript.read_text(encoding="utf-8") + "\ntampered after hashing", encoding="utf-8")
    evidence = tmp_path / "audit.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = _codex_audit_probe(tmp_path, evidence)
    assert result["status"] == "BLOCKED"
    assert any("hash does not match" in reason for reason in result["reasons"])


def test_bindings_are_parsed_not_substring_matched(tmp_path: Path) -> None:
    required = {
        "logi": "aims_workspace/skills/fullstack-repair-closure/SKILL.md",
        "traini": "aims_workspace/skills/traini-raw-material-to-pairs/SKILL.md",
        "knomi": "docs/agents/skills/knomi_knowledge.md",
        "codex-auditor": "aims_workspace/skills/engineering-team/codex-auditor/SKILL.md",
    }
    for path in required.values():
        _write(tmp_path / path, "skill")
    _write(
        tmp_path / "ops/agents/agent_skill_registry.yaml",
        "agents:\n"
        f"  logi: {{skill_packs: [{required['logi']}]}}\n"
        f"  traini: {{skill_packs: [{required['traini']}]}}\n"
        f"  knomi: {{skill_packs: [{required['knomi']}]}}\n"
        f"  codex-auditor: {{skill_packs: [{required['codex-auditor']}]}}\n",
    )
    entrypoint = tmp_path / "ops/tool_registry_mcp.py"
    _write(entrypoint, "")
    _write(
        tmp_path / "ops/nemoclaw_mcp_config.json",
        json.dumps(
            {
                "mcpServers": {
                    "aims": {
                        "command": "python3",
                        "args": [str(entrypoint)],
                        "env": {
                            "KNOMI_API_URL": "http://localhost:8768",
                            "ARGUS_API_URL": "http://localhost:8770",
                        },
                    }
                }
            }
        ),
    )
    assert _bindings_probe(tmp_path)["status"] == "PASS"
    _write(tmp_path / "ops/nemoclaw_mcp_config.json", '{"comment":"KNOMI_API_URL ARGUS_API_URL"}')
    assert _bindings_probe(tmp_path)["status"] == "BLOCKED"


def test_traini_probe_parses_disposition_and_provenance(tmp_path: Path) -> None:
    base = Path("aims_workspace/logi/traini_pair_candidates/lesson_x")
    reports = {
        "candidate_manifest.json": {
            "schema": "aims.traini.pair_candidate.v1",
            "pair_candidate_id": "candidate_x",
            "source_session_id": "sid",
            "source_lesson_id": "lesson_x",
            "raw_material_only": True,
            "direct_training_allowed": False,
        },
        "contamination_report.json": {"schema": "aims.traini.contamination_report.v1", "candidate_id": "candidate_x", "source_session_id": "sid", "source_lesson_id": "lesson_x", "status": "PASS", "direct_training_allowed": False},
        "dedup_report.json": {"schema": "aims.traini.dedup_report.v1", "candidate_id": "candidate_x", "source_session_id": "sid", "source_lesson_id": "lesson_x", "status": "PASS", "direct_training_allowed": False},
        "slot_router_report.json": {"schema": "aims.traini.slot_router_report.v1", "candidate_id": "candidate_x", "source_session_id": "sid", "source_lesson_id": "lesson_x", "status": "PASS", "training_scheduled": False, "direct_training_allowed": False},
        "dataset_gate_report.json": {"schema": "aims.traini.dataset_gate_report.v1", "candidate_id": "candidate_x", "source_session_id": "sid", "source_lesson_id": "lesson_x", "status": "REJECTED_CANDIDATE_ONLY", "dataset_admission_status": "REJECTED", "training_scheduled": False, "direct_training_allowed": False},
    }
    for name, value in reports.items():
        _write(tmp_path / base / name, json.dumps(value))
    row = {
        "source_session_id": "sid",
        "lesson_id": "lesson_x",
        "direct_training_allowed": False,
        "pair_candidate_path": str(base / "candidate_manifest.json"),
        "contamination_report_path": str(base / "contamination_report.json"),
        "dedup_report_path": str(base / "dedup_report.json"),
        "slot_router_report_path": str(base / "slot_router_report.json"),
        "dataset_gate_report_path": str(base / "dataset_gate_report.json"),
    }
    hashes = {
        key: hashlib.sha256((tmp_path / row[key]).read_bytes()).hexdigest()
        for key in (
            "pair_candidate_path",
            "contamination_report_path",
            "dedup_report_path",
            "slot_router_report_path",
            "dataset_gate_report_path",
        )
    }
    _write(
        tmp_path / base / "gate_evidence_binding.json",
        json.dumps(
            {
                "schema": "aims.traini.gate_evidence_binding.v1",
                "source_session_id": "sid",
                "source_lesson_id": "lesson_x",
                "candidate_id": "candidate_x",
                "gate_evidence_sha256": hashes,
                "direct_training_allowed": False,
                "training_scheduled": False,
            }
        ),
    )
    assert _traini_gate_probe(tmp_path, row)["status"] == "PASS"
    reports["contamination_report.json"]["status"] = "FAIL"
    _write(tmp_path / base / "contamination_report.json", json.dumps(reports["contamination_report.json"]))
    assert _traini_gate_probe(tmp_path, row)["status"] == "BLOCKED"
