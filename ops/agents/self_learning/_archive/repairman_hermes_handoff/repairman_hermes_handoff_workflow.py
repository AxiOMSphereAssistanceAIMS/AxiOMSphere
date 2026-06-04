#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .repair_case_dossier_builder import build_dossiers_from_audit
    from .repair_case_sanitizer import sanitize_obj
    from .hermes_review_prompt_builder import build_hermes_prompt
    from .repair_case_skill_signal_extractor import extract_skill_signal
    from .repairman_hermes_handoff_validator import validate
except ImportError:
    from agents.self_learning.repairman_hermes_handoff.repair_case_dossier_builder import build_dossiers_from_audit  # type: ignore
    from agents.self_learning.repairman_hermes_handoff.repair_case_sanitizer import sanitize_obj  # type: ignore
    from agents.self_learning.repairman_hermes_handoff.hermes_review_prompt_builder import build_hermes_prompt  # type: ignore
    from agents.self_learning.repairman_hermes_handoff.repair_case_skill_signal_extractor import extract_skill_signal  # type: ignore
    from agents.self_learning.repairman_hermes_handoff.repairman_hermes_handoff_validator import validate  # type: ignore


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_workflow(audit_root: Path, out_dir: Path, dry_run: bool = True, invoke_hermes: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    dossiers = build_dossiers_from_audit(audit_root)
    sanitized_count = 0
    redacted_count = 0

    sanitized_dossiers = []
    for d in dossiers:
        sanitized, redactions = sanitize_obj(d)
        sanitized["sanitized"] = True
        sanitized_dossiers.append(sanitized)
        sanitized_count += 1
        redacted_count += redactions

    prompts = [build_hermes_prompt(d) for d in sanitized_dossiers]
    signals = [extract_skill_signal(d) for d in sanitized_dossiers]

    _write_json(out_dir / "repair_case_dossiers.json", {"dossiers": sanitized_dossiers})
    _write_json(out_dir / "hermes_review_prompts.json", {"prompts": prompts})
    _write_json(out_dir / "skill_incubation_signals.json", {"signals": signals})

    val = validate(audit_root, sanitized_dossiers, prompts, signals, dry_run=dry_run)

    report = {
        "phase": "repairman_hermes_handoff",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dry_run": dry_run,
        "invoke_hermes_requested": invoke_hermes,
        "repair_cases_found": len(dossiers),
        "dossiers_created": len(dossiers),
        "dossiers_sanitized": sanitized_count,
        "hermes_prompts_created": len(prompts),
        "skill_incubation_signals_created": len(signals),
        "secrets_redacted": redacted_count,
        "model_endpoint_calls": 0,
        "hermes_invocations": 0,
        "production_patches": 0,
        "safety_status": "PASS" if val["ok"] else "FAIL",
        "next_action": "RUN_HERMES_REVIEW_MANUALLY_OR_ENABLE_SANDBOXED_REVIEW",
        "validator": val,
    }

    _write_json(out_dir / "repairman_hermes_handoff_evidence_pack.json", {
        "evidence_pack_id": f"handoff_{int(dt.datetime.now().timestamp())}",
        "created_at": report["created_at"],
        "repair_cases_found": report["repair_cases_found"],
        "dossiers_created": report["dossiers_created"],
        "dossiers_sanitized": report["dossiers_sanitized"],
        "hermes_prompts_created": report["hermes_prompts_created"],
        "skill_incubation_signals_created": report["skill_incubation_signals_created"],
        "secrets_redacted": report["secrets_redacted"],
        "model_endpoint_calls": 0,
        "hermes_invocations": 0,
        "production_patches": 0,
        "safety_status": report["safety_status"],
    })

    _write_json(out_dir / "repairman_hermes_handoff_report.json", report)
    (out_dir / "repairman_hermes_handoff_report.md").write_text("\n".join([
        "# Repairman -> Hermes Handoff Report",
        f"- repair_cases_found: {report['repair_cases_found']}",
        f"- dossiers_created: {report['dossiers_created']}",
        f"- dossiers_sanitized: {report['dossiers_sanitized']}",
        f"- hermes_prompts_created: {report['hermes_prompts_created']}",
        f"- skill_incubation_signals_created: {report['skill_incubation_signals_created']}",
        f"- secrets_redacted: {report['secrets_redacted']}",
        f"- model_endpoint_calls: {report['model_endpoint_calls']}",
        f"- hermes_invocations: {report['hermes_invocations']}",
        f"- production_patches: {report['production_patches']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--invoke-hermes", action="store_true")
    args = ap.parse_args()

    report = run_workflow(args.audit_root, args.out, dry_run=args.dry_run or not args.invoke_hermes, invoke_hermes=args.invoke_hermes)

    print(f"repair_cases_found               : {report['repair_cases_found']}")
    print(f"dossiers_created                 : {report['dossiers_created']}")
    print(f"dossiers_sanitized               : {report['dossiers_sanitized']}")
    print(f"hermes_prompts_created           : {report['hermes_prompts_created']}")
    print(f"skill_incubation_signals_created : {report['skill_incubation_signals_created']}")
    print(f"secrets_redacted                 : {report['secrets_redacted']}")
    print(f"model_endpoint_calls             : {report['model_endpoint_calls']}")
    print(f"hermes_invocations               : {report['hermes_invocations']}")
    print(f"production_patches               : {report['production_patches']}")
    print(f"safety_status                    : {report['safety_status']}")
    print(f"next_action                      : {report['next_action']}")

    return 0 if report["safety_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
