#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .agent_self_learning_profile import build_profiles
    from .agent_observation_buffer import build_observation_buffers
    from .agent_skill_request_emitter import build_skill_request_outboxes
    from .agent_skill_usage_monitor import build_skill_usage_monitors
    from .agent_skill_improvement_cycle import build_improvement_cycles
    from .agent_loop_state_store import build_loop_states
    from .agent_loop_policy import central_boundary
    from .per_agent_loop_validator import verify_phase27_acceptance, validate_outputs
except ImportError:
    from agents.self_learning.per_agent_loop.agent_self_learning_profile import build_profiles  # type: ignore
    from agents.self_learning.per_agent_loop.agent_observation_buffer import build_observation_buffers  # type: ignore
    from agents.self_learning.per_agent_loop.agent_skill_request_emitter import build_skill_request_outboxes  # type: ignore
    from agents.self_learning.per_agent_loop.agent_skill_usage_monitor import build_skill_usage_monitors  # type: ignore
    from agents.self_learning.per_agent_loop.agent_skill_improvement_cycle import build_improvement_cycles  # type: ignore
    from agents.self_learning.per_agent_loop.agent_loop_state_store import build_loop_states  # type: ignore
    from agents.self_learning.per_agent_loop.agent_loop_policy import central_boundary  # type: ignore
    from agents.self_learning.per_agent_loop.per_agent_loop_validator import verify_phase27_acceptance, validate_outputs  # type: ignore


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_workflow(root: Path, out_dir: Path) -> dict:
    ok, issues = verify_phase27_acceptance(root)
    if not ok:
        raise RuntimeError("Phase 27 acceptance failed: " + "; ".join(issues))

    out_dir.mkdir(parents=True, exist_ok=True)
    root_str = str(root / "aims_workspace/agent_self_learning")
    profiles = build_profiles(root_str)
    buffers = build_observation_buffers(profiles)
    outboxes = build_skill_request_outboxes(profiles, buffers)
    monitors = build_skill_usage_monitors(profiles)
    cycles = build_improvement_cycles(monitors)
    states = build_loop_states(profiles, buffers, outboxes, monitors, cycles)
    policy = central_boundary()

    _write(out_dir / "agent_self_learning_profiles.json", {"profiles": profiles})
    _write(out_dir / "agent_loop_states.json", {"states": states})
    _write(out_dir / "agent_observation_buffers.json", {"buffers": buffers})
    _write(out_dir / "agent_skill_request_outbox.json", {"outboxes": outboxes})
    _write(out_dir / "agent_skill_usage_monitoring.json", {"monitors": monitors})
    _write(out_dir / "agent_skill_improvement_cycles.json", {"cycles": cycles})

    validation = validate_outputs({
        "profiles": profiles,
        "states": states,
        "outboxes": outboxes,
        "cycles": cycles,
        "policy": policy,
    })

    report = {
        "agents_profiled": len(profiles),
        "agent_loop_states_created": len(states),
        "observation_buffers_created": len(buffers),
        "skill_request_outboxes_created": len(outboxes),
        "skill_usage_monitors_created": len(monitors),
        "improvement_cycles_created": len(cycles),
        "central_runner_created": policy.get("central_runner_created", False),
        "self_approval_count": 0,
        "uncontrolled_autonomy_count": 0,
        "safety_status": "PASS" if validation["ok"] else "FAIL",
        "next_action": "WIRE_AGENT_LOCAL_LOOPS_TO_EXISTING_AGENT_ENTRYPOINTS" if validation["ok"] else "FIX_PER_AGENT_LOOP_VALIDATION",
        "central_boundary": policy,
        "validation_errors": validation["errors"],
    }

    _write(out_dir / "per_agent_loop_report.json", report)
    (out_dir / "per_agent_loop_report.md").write_text("\n".join([
        "# Per-Agent Self-Learning Loop Report",
        f"- agents_profiled: {report['agents_profiled']}",
        f"- central_runner_created: {report['central_runner_created']}",
        f"- self_approval_count: {report['self_approval_count']}",
        f"- uncontrolled_autonomy_count: {report['uncontrolled_autonomy_count']}",
        f"- safety_status: {report['safety_status']}",
        f"- next_action: {report['next_action']}",
    ]), encoding="utf-8")

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("aims_workspace/agent_self_learning"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[4]
    root = repo_root if not args.root.is_absolute() else args.root
    report = run_workflow(root, args.out)

    keys = [
        "agents_profiled",
        "agent_loop_states_created",
        "observation_buffers_created",
        "skill_request_outboxes_created",
        "skill_usage_monitors_created",
        "improvement_cycles_created",
        "central_runner_created",
        "self_approval_count",
        "uncontrolled_autonomy_count",
        "safety_status",
        "next_action",
    ]
    for k in keys:
        print(f"{k:30}: {report.get(k)}")
    return 0 if report.get("safety_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
