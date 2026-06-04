#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from .certification_package_builder import build_package
    from .certification_gate_checklist_builder import build_gate_checklist
    from .certification_review_queue_writer import build_review_queue
    from .certification_intake_evidence_writer import build_evidence_pack
    from .certification_intake_validator import verify_phase23_acceptance, validate_outputs
except ImportError:
    from agents.self_learning.automatic_certification_intake.certification_package_builder import build_package  # type: ignore
    from agents.self_learning.automatic_certification_intake.certification_gate_checklist_builder import build_gate_checklist  # type: ignore
    from agents.self_learning.automatic_certification_intake.certification_review_queue_writer import build_review_queue  # type: ignore
    from agents.self_learning.automatic_certification_intake.certification_intake_evidence_writer import build_evidence_pack  # type: ignore
    from agents.self_learning.automatic_certification_intake.certification_intake_validator import verify_phase23_acceptance, validate_outputs  # type: ignore


def _dangerous_zero(ex: dict) -> bool:
    return all(
        int(ex.get(k, 0)) == 0
        for k in (
            "model_endpoint_calls",
            "training_launch_count",
            "model_load_unload_count",
            "service_restart_count",
            "secrets_access_count",
            "raw_claude_mem_access_count",
            "active_registry_modification_count",
        )
    )


def run_workflow(execution_results_path: Path, execution_evidence_path: Path, cert_queue_path: Path, out_dir: Path) -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ok23, errs23 = verify_phase23_acceptance(repo_root)
    if not ok23:
        raise RuntimeError(f"Phase23 acceptance failed: {errs23}")

    out_dir.mkdir(parents=True, exist_ok=True)

    execution_results = json.loads(execution_results_path.read_text(encoding="utf-8")).get("executions", [])
    _ = json.loads(execution_evidence_path.read_text(encoding="utf-8"))
    cert_queue = json.loads(cert_queue_path.read_text(encoding="utf-8"))

    if cert_queue.get("execution_allowed") is not False:
        raise RuntimeError("Phase23 certification intake queue execution_allowed must be false")

    ready_ids = {
        i.get("execution_id")
        for i in cert_queue.get("queued_items", [])
        if i.get("status") == "READY_FOR_CERTIFICATION_REVIEW"
    }

    eligible = []
    skipped = 0
    for ex in execution_results:
        if ex.get("execution_id") not in ready_ids:
            skipped += 1
            continue
        if ex.get("result_status") not in {"SANDBOX_PASS", "SANDBOX_WARN"}:
            skipped += 1
            continue
        if ex.get("lifecycle_state_after") != "SANDBOX_SKILL":
            skipped += 1
            continue
        if ex.get("runtime_activation_allowed") is not False or ex.get("self_approval_allowed") is not False:
            skipped += 1
            continue
        if not _dangerous_zero(ex):
            skipped += 1
            continue
        eligible.append(ex)

    packages = [build_package(ex) for ex in eligible]
    checklists = [build_gate_checklist(p) for p in packages]
    review_queue = build_review_queue(packages)

    evidence = build_evidence_pack(
        source_phase23_artifacts=[
            str(execution_results_path),
            str(execution_evidence_path),
            str(cert_queue_path),
        ],
        execution_results_loaded=len(execution_results),
        certification_candidates_created=len(packages),
        gate_checklists_created=len(checklists),
        review_queue_items_created=len(review_queue.get("queued_items", [])),
        skipped_results=skipped,
        certification_review_queue_path=str(out_dir / "certification_review_queue.json"),
    )

    val = validate_outputs(packages, checklists, review_queue)

    (out_dir / "certification_candidate_packages.json").write_text(json.dumps({"packages": packages}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "certification_gate_checklists.json").write_text(json.dumps({"gate_checklists": checklists}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "certification_review_queue.json").write_text(json.dumps(review_queue, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "certification_intake_evidence_pack.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    report = {
        "phase": "24",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "execution_results_loaded": len(execution_results),
        "eligible_results": len(eligible),
        "certification_candidates_created": len(packages),
        "gate_checklists_created": len(checklists),
        "review_queue_items_created": len(review_queue.get("queued_items", [])),
        "skipped_results": skipped,
        "runtime_activation_count": val["runtime_activation_count"],
        "active_registry_modification_count": val["active_registry_modification_count"],
        "model_endpoint_calls": val["model_endpoint_calls"],
        "training_launch_count": val["training_launch_count"],
        "model_load_unload_count": val["model_load_unload_count"],
        "service_restart_count": val["service_restart_count"],
        "safety_status": "PASS" if val.get("ok") else "FAIL",
        "next_action": "AUTOMATIC_CERTIFICATION_GATE_REVIEW",
        "validator": val,
    }

    (out_dir / "certification_intake_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "certification_intake_report.md").write_text("\n".join([
        "# AIMS Phase 24 — Automatic Certification Intake",
        "",
        f"- execution_results_loaded: {report['execution_results_loaded']}",
        f"- eligible_results: {report['eligible_results']}",
        f"- certification_candidates_created: {report['certification_candidates_created']}",
        f"- gate_checklists_created: {report['gate_checklists_created']}",
        f"- review_queue_items_created: {report['review_queue_items_created']}",
        f"- skipped_results: {report['skipped_results']}",
        f"- runtime_activation_count: {report['runtime_activation_count']}",
        f"- active_registry_modification_count: {report['active_registry_modification_count']}",
        f"- model_endpoint_calls: {report['model_endpoint_calls']}",
        f"- training_launch_count: {report['training_launch_count']}",
        f"- model_load_unload_count: {report['model_load_unload_count']}",
        f"- service_restart_count: {report['service_restart_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]) + "\n", encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="AIMS Phase 24 automatic certification intake workflow")
    ap.add_argument("--execution-results", required=True, type=Path)
    ap.add_argument("--execution-evidence", required=True, type=Path)
    ap.add_argument("--certification-queue", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    r = run_workflow(args.execution_results, args.execution_evidence, args.certification_queue, args.out)
    print(f"execution_results_loaded      : {r['execution_results_loaded']}")
    print(f"eligible_results             : {r['eligible_results']}")
    print(f"certification_candidates_created: {r['certification_candidates_created']}")
    print(f"gate_checklists_created      : {r['gate_checklists_created']}")
    print(f"review_queue_items_created   : {r['review_queue_items_created']}")
    print(f"skipped_results              : {r['skipped_results']}")
    print(f"runtime_activation_count     : {r['runtime_activation_count']}")
    print(f"active_registry_modification_count: {r['active_registry_modification_count']}")
    print(f"model_endpoint_calls         : {r['model_endpoint_calls']}")
    print(f"training_launch_count        : {r['training_launch_count']}")
    print(f"model_load_unload_count      : {r['model_load_unload_count']}")
    print(f"service_restart_count        : {r['service_restart_count']}")
    print(f"safety_status                : {r['safety_status']}")
    print(f"next_action                  : {r['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
