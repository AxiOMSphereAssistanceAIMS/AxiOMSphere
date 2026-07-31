#!/usr/bin/env python3
"""Executable Codex learning closure and 24h-certification preflight.

The runner is deliberately bounded: it never starts training, mutates a model
registry, deletes raw material, or starts 24-hour certification.  It turns
replayable ledger chains into compact Knomi lesson cards, proves retrieval,
advances their lifecycle, and reports every remaining blocker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.knomi.codex_lesson_bridge import probe_session_card, publish_capture_failure_card, publish_session_card
from ops.logi.artifact_lifecycle import audit as audit_lifecycle
from ops.logi.artifact_lifecycle import lifecycle_for_session
from ops.logi.codex_learning_traceability import replay_traceability_ledger
from ops.logi.stale_codex_session_reaper import reap


PAIR_GATE_KEYS = (
    "contamination_report_path",
    "dedup_report_path",
    "slot_router_report_path",
    "dataset_gate_report_path",
)
AUDIT_SCHEMA = "aims.codex_cli.closed_loop_audit.v1"
AUDIT_SCOPE = (
    "ops/logi/artifact_lifecycle.py",
    "ops/logi/raw_material_clearance.py",
    "ops/logi/stale_codex_session_reaper.py",
    "ops/logi/run_codex_learning_once.py",
    "ops/logi/closed_loop.py",
    "ops/knomi/common.py",
    "ops/knomi/codex_lesson_bridge.py",
    "ops/tool_registry_mcp.py",
)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
AUDIT_REQUIRED_KEYS = {
    "schema",
    "generated_at_utc",
    "auditor_tool",
    "verdict",
    "blocking_findings",
    "non_blocking_findings",
    "audit_scope",
    "audited_files_sha256",
    "invariants",
    "certification_recommendation",
    "tests",
    "summary",
}
# A hand-authored JSON matching the schema is not sufficient for an audit PASS;
# the result must be anchored to a real, non-trivial Codex CLI transcript.
_MIN_RAW_TRANSCRIPT_BYTES = 2000


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _ledger_inventory(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if path.exists():
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except Exception as exc:
                errors.append(f"line {line_number}: malformed JSON: {exc}")
                continue
            if not isinstance(value, dict) or not value.get("source_session_id"):
                errors.append(f"line {line_number}: object/source_session_id missing")
                continue
            session_id = str(value["source_session_id"])
            if SESSION_ID_RE.fullmatch(session_id) is None:
                errors.append(f"line {line_number}: unsafe source_session_id")
                continue
            if session_id in rows:
                previous_semantic = {k: v for k, v in rows[session_id].items() if k != "recorded_at"}
                current_semantic = {k: v for k, v in value.items() if k != "recorded_at"}
                if previous_semantic != current_semantic:
                    errors.append(f"line {line_number}: conflicting duplicate session {session_id}")
                continue
            rows[session_id] = value
    else:
        errors.append("ledger file missing")
    if not rows:
        errors.append("ledger contains no valid sessions")
    return [rows[key] for key in sorted(rows)], errors


def _artifact_path(root: Path, row: dict[str, Any], key: str) -> Path | None:
    value = str(row.get(key) or "")
    if not value:
        return None
    path = root / value
    if path.is_file():
        return path
    session_id = str(row.get("source_session_id") or "")
    prefix = f"aims_workspace/logi/raw_material/codex_sessions/{session_id}/"
    if value.startswith(prefix):
        retained = root / "aims_workspace/logi/retained_evidence/codex_sessions" / session_id / value.removeprefix(prefix)
        return retained if retained.is_file() else None
    return None


def _traini_gate_probe(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    pair_required = bool(row.get("pair_candidate_path"))
    if not pair_required:
        safe = row.get("direct_training_allowed") is False
        return {
            "status": "PASS" if safe else "BLOCKED",
            "pair_required": False,
            "missing_gate_evidence": [],
            "invalid_gate_evidence": [] if safe else ["ledger permits direct training"],
            "gate_evidence_sha256": {},
            "direct_training_allowed": row.get("direct_training_allowed"),
            "training_started": False,
        }

    session_id = str(row.get("source_session_id") or "")
    paths = {key: _artifact_path(root, row, key) for key in PAIR_GATE_KEYS}
    candidate_path = _artifact_path(root, row, "pair_candidate_path")
    missing = [key for key, path in paths.items() if path is None]
    if candidate_path is None:
        missing.append("pair_candidate_path")
    invalid: list[str] = []
    reports = {key: _read(path) if path else {} for key, path in paths.items()}
    candidate = _read(candidate_path) if candidate_path else {}
    candidate_id = str(candidate.get("pair_candidate_id") or candidate.get("candidate_id") or "")
    lesson_id = str(row.get("lesson_id") or "")
    if candidate:
        source = candidate.get("source_session_id") or (candidate.get("provenance") or {}).get("source_session_id")
        if source != session_id:
            invalid.append("candidate session provenance mismatch")
        if candidate.get("source_lesson_id") != lesson_id:
            invalid.append("candidate lesson provenance mismatch")
        if candidate.get("raw_material_only") is not True:
            invalid.append("candidate is not marked raw_material_only")
        if candidate.get("direct_training_allowed") is not False:
            invalid.append("candidate permits direct training")
    expected_status = {
        "contamination_report_path": {"PASS"},
        "dedup_report_path": {"PASS"},
        "slot_router_report_path": {"PASS"},
        "dataset_gate_report_path": {"REJECTED_CANDIDATE_ONLY"},
    }
    expected_schema = {
        "contamination_report_path": "aims.traini.contamination_report.v1",
        "dedup_report_path": "aims.traini.dedup_report.v1",
        "slot_router_report_path": "aims.traini.slot_router_report.v1",
        "dataset_gate_report_path": "aims.traini.dataset_gate_report.v1",
    }
    if candidate and candidate.get("schema") != "aims.traini.pair_candidate.v1":
        invalid.append("candidate schema mismatch")
    for key, report in reports.items():
        if not report:
            continue
        if str(report.get("status") or "").upper() not in expected_status[key]:
            invalid.append(f"{key} disposition is not passing/safe")
        if report.get("schema") != expected_schema[key]:
            invalid.append(f"{key} schema mismatch")
        if candidate_id and report.get("candidate_id") != candidate_id:
            invalid.append(f"{key} candidate provenance mismatch")
        report_session = report.get("source_session_id")
        if report_session != session_id:
            invalid.append(f"{key} session provenance mismatch")
        if report.get("source_lesson_id") != lesson_id:
            invalid.append(f"{key} lesson provenance mismatch")
        if report.get("direct_training_allowed") is not False:
            invalid.append(f"{key} permits direct training")
        if report.get("training_scheduled") not in (None, False):
            invalid.append(f"{key} schedules training")
    dataset = reports["dataset_gate_report_path"]
    if dataset and dataset.get("dataset_admission_status") != "REJECTED":
        invalid.append("dataset gate did not reject direct admission")
    hashes = {
        key: _sha256(path)
        for key, path in {**paths, "pair_candidate_path": candidate_path}.items()
        if path is not None
    }
    binding_path = candidate_path.parent / "gate_evidence_binding.json" if candidate_path else None
    binding = _read(binding_path) if binding_path else {}
    if (
        binding.get("schema") != "aims.traini.gate_evidence_binding.v1"
        or binding.get("source_session_id") != session_id
        or binding.get("source_lesson_id") != lesson_id
        or binding.get("candidate_id") != candidate_id
        or binding.get("gate_evidence_sha256") != hashes
        or binding.get("direct_training_allowed") is not False
        or binding.get("training_scheduled") is not False
    ):
        invalid.append("gate evidence hashes are not bound by the integrity manifest")
    safe = not missing and not invalid and row.get("direct_training_allowed") is False
    return {
        "status": "PASS" if safe else "BLOCKED",
        "pair_required": True,
        "missing_gate_evidence": missing,
        "invalid_gate_evidence": invalid,
        "gate_evidence_sha256": hashes,
        "gate_evidence_binding_path": str(binding_path) if binding_path else None,
        "direct_training_allowed": row.get("direct_training_allowed"),
        "training_started": False,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_evidence(
    root: Path,
    session_id: str,
    checks: dict[str, bool],
    paths: dict[str, Path],
) -> dict[str, dict[str, str]]:
    supporting = {}
    for name, path in paths.items():
        supporting[name] = {
            "status": "PASS" if checks[name] else "BLOCKED",
            "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
            "sha256": _sha256(path) if path.is_file() else "",
        }
    probe_path = root / "aims_workspace/logi/benefit_probes" / f"{session_id}.json"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text(
        json.dumps(
            {
                "schema": "aims.closed_loop.benefit_probe.v1",
                "source_session_id": session_id,
                "checks": checks,
                "supporting_evidence": supporting,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    digest = _sha256(probe_path)
    relative = str(probe_path.relative_to(root))
    return {name: {"status": "PASS", "path": relative, "sha256": digest} for name in checks}


def _codex_audit_probe(root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "MISSING", "reason": "fresh Codex CLI audit evidence was not supplied"}
    data = _read(path)
    reasons: list[str] = []
    if set(data) != AUDIT_REQUIRED_KEYS:
        reasons.append("audit object does not have the exact required top-level fields")
    if data.get("schema") != AUDIT_SCHEMA:
        reasons.append("unrecognized audit schema")
    if str(data.get("auditor_tool") or "").lower().find("codex cli") < 0:
        reasons.append("auditor tool identity is not Codex CLI")
    if str(data.get("verdict") or "").upper() != "PASS" or data.get("blocking_findings") != []:
        reasons.append("audit verdict is not clean PASS")
    invariants = data.get("invariants")
    if not isinstance(invariants, dict) or not invariants or not all(value is True for value in invariants.values()):
        reasons.append("audit invariants are missing or not all true")
    if not isinstance(data.get("non_blocking_findings"), list):
        reasons.append("audit non-blocking findings are missing")
    if data.get("certification_recommendation") != "READY_FOR_24H_CERTIFICATION":
        reasons.append("audit certification recommendation is not ready")
    if not isinstance(data.get("tests"), dict) or not data.get("tests"):
        reasons.append("audit tests evidence is missing")
    if not isinstance(data.get("summary"), str) or not data.get("summary").strip():
        reasons.append("audit summary is missing")
    try:
        generated = datetime.fromisoformat(str(data.get("generated_at_utc")))
        current = datetime.now(timezone.utc)
        if generated.tzinfo is None or generated < current - timedelta(hours=2) or generated > current + timedelta(minutes=5):
            reasons.append("audit evidence is stale or future-dated")
    except (TypeError, ValueError):
        reasons.append("audit timestamp missing or invalid")
    scope = data.get("audit_scope")
    if scope != list(AUDIT_SCOPE):
        reasons.append("audit scope does not match required implementation scope")
    hashes = data.get("audited_files_sha256")
    expected_hashes = {name: _sha256(root / name) for name in AUDIT_SCOPE if (root / name).is_file()}
    if not isinstance(hashes, dict) or hashes != expected_hashes or len(expected_hashes) != len(AUDIT_SCOPE):
        reasons.append("audited content hashes do not match current implementation")
    raw_transcript = data.get("raw_transcript")
    if isinstance(raw_transcript, dict):
        transcript_path = Path(str(raw_transcript.get("path", "")))
        if not transcript_path.is_file():
            reasons.append("raw Codex CLI transcript file does not exist")
        elif transcript_path.stat().st_size < _MIN_RAW_TRANSCRIPT_BYTES:
            reasons.append("raw Codex CLI transcript is implausibly small for a real audit session")
        elif _sha256(transcript_path) != raw_transcript.get("sha256"):
            reasons.append("raw Codex CLI transcript hash does not match recorded evidence")
    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "path": str(path),
        "verdict": str(data.get("verdict") or "MISSING").upper(),
        "reasons": reasons,
    }


def _bindings_probe(root: Path) -> dict[str, Any]:
    registry_path = root / "ops/agents/agent_skill_registry.yaml"
    mcp_path = root / "ops/nemoclaw_mcp_config.json"
    errors: list[str] = []
    try:
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        registry = {}
        errors.append(f"skill registry invalid: {exc}")
    agents = registry.get("agents") if isinstance(registry, dict) else {}
    required_packs = {
        "logi": "aims_workspace/skills/fullstack-repair-closure/SKILL.md",
        "traini": "aims_workspace/skills/traini-raw-material-to-pairs/SKILL.md",
        "knomi": "docs/agents/skills/knomi_knowledge.md",
        "codex-auditor": "aims_workspace/skills/engineering-team/codex-auditor/SKILL.md",
    }
    for agent, required_pack in required_packs.items():
        entry = agents.get(agent) if isinstance(agents, dict) else None
        packs = entry.get("skill_packs") if isinstance(entry, dict) else None
        if not isinstance(packs, list) or not packs:
            errors.append(f"required agent skill binding missing: {agent}")
            continue
        if required_pack not in packs:
            errors.append(f"required exact skill binding missing: {agent} -> {required_pack}")
        missing = [str(pack) for pack in packs if not (root / str(pack)).is_file()]
        if missing:
            errors.append(f"{agent} skill files missing: {missing}")
    try:
        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    except Exception as exc:
        mcp = {}
        errors.append(f"MCP config invalid: {exc}")
    aims = (mcp.get("mcpServers") or {}).get("aims") if isinstance(mcp, dict) else None
    if not isinstance(aims, dict) or aims.get("command") != "python3":
        errors.append("AIMS MCP server command missing")
    else:
        args = aims.get("args")
        expected_entrypoint = (root / "ops/tool_registry_mcp.py").resolve()
        if (
            not isinstance(args, list)
            or len(args) != 1
            or Path(str(args[0])).resolve() != expected_entrypoint
            or not expected_entrypoint.is_file()
        ):
            errors.append("AIMS MCP server entrypoint missing")
        env = aims.get("env")
        for key in ("KNOMI_API_URL", "ARGUS_API_URL"):
            value = env.get(key) if isinstance(env, dict) else None
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                errors.append(f"MCP endpoint missing or invalid: {key}")
    return {"status": "PASS" if not errors else "BLOCKED", "errors": errors}


def _terminal_quarantined_captures(root: Path, ledger_ids: set[str]) -> list[dict[str, Any]]:
    validation_root = root / "aims_workspace/logi/validation/codex_sessions"
    raw_root = root / "aims_workspace/logi/raw_material/codex_sessions"
    rows: list[dict[str, Any]] = []
    for report_path in sorted(validation_root.glob("*/validation_report.json")):
        session_id = report_path.parent.name
        if session_id in ledger_ids:
            continue
        validation = _read(report_path)
        final_status = _read(raw_root / session_id / "final_status.json")
        manifest = _read(raw_root / session_id / "session_manifest.json")
        if validation.get("lifecycle_state") not in {"QUARANTINED_INCOMPLETE", "QUARANTINED_INVALID"}:
            continue
        if str(manifest.get("status") or "").upper() not in {"FAILED", "COMPLETED"}:
            continue
        if str(final_status.get("status") or "").upper() not in {"FAILED", "COMPLETED"}:
            continue
        rows.append(
            {
                "session_id": session_id,
                "validation": validation,
                "final_status": final_status,
                "source_path": f"aims_workspace/logi/raw_material/codex_sessions/{session_id}",
                "evidence": [
                    str(report_path.relative_to(root)),
                    f"aims_workspace/logi/raw_material/codex_sessions/{session_id}/final_status.json",
                    f"aims_workspace/logi/raw_material/codex_sessions/{session_id}/session_manifest.json",
                ],
            }
        )
    return rows


def run_closed_loop(root: Path, *, apply_benefit: bool, codex_audit_evidence: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    rows, ledger_errors = _ledger_inventory(root)
    global_replay = {"status": "FAIL", "reason": "ledger inventory invalid"} if ledger_errors else replay_traceability_ledger(root)
    global_ledger_clean = not ledger_errors and global_replay.get("status") == "PASS"
    sessions: list[dict[str, Any]] = []
    for row in rows:
        session_id = str(row["source_session_id"])
        replay = replay_traceability_ledger(root, session_id=session_id)
        traini = _traini_gate_probe(root, row)
        if apply_benefit and global_ledger_clean and replay.get("status") == "PASS" and traini["status"] == "PASS":
            knomi_publish = publish_session_card(root, session_id)
        else:
            probe = probe_session_card(root, session_id)
            knomi_publish = {"status": "PASS" if probe["retrievable"] else "MISSING", "probe": probe}
        knomi_probe = knomi_publish.get("probe") or {}
        checks = {
            "ledger_replay": replay.get("status") == "PASS",
            "traini_gate_trace": traini["status"] == "PASS",
            "knomi_retrieval": knomi_publish.get("status") == "PASS" and bool(knomi_probe.get("retrievable")),
            "raw_transcript_excluded_from_knomi": knomi_probe.get("raw_transcript_indexed") is False,
        }
        card_path = Path(str(knomi_publish.get("card_path") or (root / "aims_workspace/knowledge/codex_lessons" / f"{session_id}.json")))
        benefit_evidence = (
            _probe_evidence(
                root,
                session_id,
                checks,
                {
                    "ledger_replay": root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl",
                    "traini_gate_trace": Path(str(traini.get("gate_evidence_binding_path") or "")),
                    "knomi_retrieval": card_path,
                    "raw_transcript_excluded_from_knomi": card_path,
                },
            )
            if apply_benefit and global_ledger_clean
            else {}
        )
        lifecycle = None
        if apply_benefit and global_ledger_clean:
            lifecycle = lifecycle_for_session(
                root,
                session_id=session_id,
                source_path=f"aims_workspace/logi/raw_material/codex_sessions/{session_id}",
                owner="Logi",
                evidence=[str(v) for k, v in row.items() if k.endswith("_path") and v],
                benefit="verified lesson is retrievable by Knomi and Traini gate trace is complete",
                result="compact runtime knowledge applied; raw transcript excluded",
                benefit_checks=checks,
                benefit_evidence=benefit_evidence,
                quarantined=False,
            )
        sessions.append(
            {
                "session_id": session_id,
                "status": "PASS" if all(checks.values()) else "BLOCKED",
                "checks": checks,
                "traini": traini,
                "knomi": knomi_publish,
                "lifecycle_state": lifecycle.get("state") if lifecycle else None,
            }
        )

    ledger_ids = {str(row["source_session_id"]) for row in rows}
    for capture in _terminal_quarantined_captures(root, ledger_ids):
        session_id = capture["session_id"]
        if apply_benefit and global_ledger_clean:
            knomi_publish = publish_capture_failure_card(
                root,
                session_id,
                validation_report=capture["validation"],
                final_status=capture["final_status"],
            )
        else:
            probe = probe_session_card(root, session_id)
            knomi_publish = {"status": "PASS" if probe["retrievable"] else "MISSING", "probe": probe}
        probe = knomi_publish.get("probe") or {}
        checks = {
            "terminal_rejection": True,
            "operational_lesson_published": knomi_publish.get("status") == "PASS",
            "knomi_retrieval": bool(probe.get("retrievable")),
            "raw_transcript_excluded_from_knomi": probe.get("raw_transcript_indexed") is False,
            "traini_rejection_enforced": capture["final_status"].get("direct_training_allowed") is False,
        }
        card_path = Path(str(knomi_publish.get("card_path") or (root / "aims_workspace/knowledge/codex_lessons" / f"{session_id}.json")))
        validation_path = root / capture["evidence"][0]
        final_path = root / capture["evidence"][1]
        benefit_evidence = (
            _probe_evidence(
                root,
                session_id,
                checks,
                {
                    "terminal_rejection": validation_path,
                    "operational_lesson_published": card_path,
                    "knomi_retrieval": card_path,
                    "raw_transcript_excluded_from_knomi": card_path,
                    "traini_rejection_enforced": final_path,
                },
            )
            if apply_benefit and global_ledger_clean
            else {}
        )
        lifecycle = None
        if apply_benefit and global_ledger_clean:
            lifecycle = lifecycle_for_session(
                root,
                session_id=session_id,
                source_path=capture["source_path"],
                owner="Logi",
                evidence=capture["evidence"],
                benefit="incomplete capture converted into a retrievable prevention rule",
                result="rejected from Traini; compact failure lesson applied",
                benefit_checks=checks,
                benefit_evidence=benefit_evidence,
                quarantined=True,
            )
        sessions.append(
            {
                "session_id": session_id,
                "status": "PASS" if all(checks.values()) else "BLOCKED",
                "kind": "TERMINAL_CAPTURE_REJECTION",
                "checks": checks,
                "knomi": knomi_publish,
                "lifecycle_state": lifecycle.get("state") if lifecycle else None,
            }
        )

    stale = reap(root, max_age_seconds=3600, apply=False)
    lifecycle = audit_lifecycle(root)
    bindings = _bindings_probe(root)
    codex = _codex_audit_probe(root, codex_audit_evidence)
    raw_root = root / "aims_workspace/logi/raw_material/codex_sessions"
    evaluated_ids = {s["session_id"] for s in sessions}
    unevaluated_terminal: list[str] = []
    active_bounded: list[str] = []
    for session_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()) if raw_root.exists() else []:
        manifest = _read(session_dir / "session_manifest.json")
        status = str(manifest.get("status") or "").upper()
        if session_dir.name in evaluated_ids:
            continue
        if status == "RUNNING":
            active_bounded.append(session_dir.name)
        else:
            unevaluated_terminal.append(session_dir.name)
    blockers: list[str] = []
    blocked_sessions = [s["session_id"] for s in sessions if s["status"] != "PASS"]
    if blocked_sessions:
        blockers.append(f"{len(blocked_sessions)} evaluated sessions lack verified downstream benefit")
    if ledger_errors or global_replay.get("status") != "PASS":
        blockers.append("global ledger inventory/replay is not clean")
    if unevaluated_terminal:
        blockers.append(f"{len(unevaluated_terminal)} terminal raw sessions lack evaluated disposition")
    if stale["count"]:
        blockers.append(f"{stale['count']} stale RUNNING Codex sessions require terminal closure")
    if lifecycle["status"] != "PASS":
        blockers.append(f"{len(lifecycle['blockers'])} artifact lifecycle records are non-terminal")
    if bindings["status"] != "PASS":
        blockers.append("AIMS skill/MCP bindings are incomplete")
    if codex["status"] != "PASS":
        blockers.append("fresh Codex CLI audit has not passed")
    report = {
        "schema": "aims.closed_learning_loop.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "APPLY_BENEFIT" if apply_benefit else "INSPECT",
        "status": "READY_FOR_24H_CERTIFICATION" if not blockers else "NOT_READY_FOR_24H_CERTIFICATION",
        "certification_started": False,
        "destructive_cleanup_performed": False,
        "training_started": False,
        "production_database_mutated": False,
        "implementation_sha256": {
            name: _sha256(root / name) for name in AUDIT_SCOPE
        },
        "application_mutations": {
            "performed": apply_benefit,
            "knowledge_cards_written_or_refreshed": len(sessions) if apply_benefit and global_ledger_clean else 0,
            "typed_benefit_probe_reports_written": len(sessions) if apply_benefit and global_ledger_clean else 0,
            "lifecycle_records_evaluated_or_advanced": len(sessions) if apply_benefit and global_ledger_clean else 0,
            "raw_material_deleted": 0,
            "training_or_certification_started": 0,
        },
        "sessions_total": len(sessions),
        "sessions_passed": len(sessions) - len(blocked_sessions),
        "sessions": sessions,
        "ledger_gate": {
            "status": "PASS" if global_ledger_clean else "BLOCKED",
            "semantic_unique_rows": len(rows),
            "global_replay_chain_count": len(global_replay.get("chains") or []),
            "errors": ledger_errors,
            "global_replay": global_replay,
        },
        "raw_disposition_gate": {"status": "PASS" if not unevaluated_terminal else "BLOCKED", "unevaluated_terminal": unevaluated_terminal, "active_bounded_not_yet_material": active_bounded},
        "stale_session_gate": stale,
        "artifact_lifecycle_gate": lifecycle,
        "bindings_gate": bindings,
        "codex_cli_audit_gate": codex,
        "blockers": blockers,
        "next_action": "start bounded 24h certification only after an explicit operator signal" if not blockers else "remediate blockers and rerun preflight",
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    blockers = report.get("blockers") or []
    blocker_lines = "\n".join(f"- {item}" for item in blockers) if blockers else "- Нет."
    return (
        "# Closed-loop certification preflight\n\n"
        f"Generated: {report['generated_at_utc']}\n\n"
        f"Status: **{report['status']}**\n\n"
        f"- Ledger sessions: {report['sessions_passed']}/{report['sessions_total']} benefit-verified\n"
        f"- Stale RUNNING: {report['stale_session_gate']['count']}\n"
        f"- Lifecycle gate: {report['artifact_lifecycle_gate']['status']}\n"
        f"- Codex CLI audit: {report['codex_cli_audit_gate']['status']}\n"
        f"- Certification started: {report['certification_started']}\n"
        f"- Destructive cleanup performed: {report['destructive_cleanup_performed']}\n\n"
        "## Blockers\n\n"
        f"{blocker_lines}\n\n"
        "## Decision rationale\n\n"
        "Readiness is fail-closed: artifacts alone do not count as benefit. Every ledger chain must pass "
        "replay, Traini gate trace, compact Knomi retrieval, raw-transcript exclusion, lifecycle closure, "
        "and a fresh Codex CLI audit.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply-benefit", action="store_true")
    parser.add_argument("--codex-audit-evidence", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()
    report = run_closed_loop(args.workspace, apply_benefit=args.apply_benefit, codex_audit_evidence=args.codex_audit_evidence)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "blockers": report["blockers"]}, ensure_ascii=False))
    return 0 if report["status"] == "READY_FOR_24H_CERTIFICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
