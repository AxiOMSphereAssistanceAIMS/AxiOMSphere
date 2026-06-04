#!/usr/bin/env python3
"""
AIMS Skill Request Approval Workflow

Purpose:
- Agent submits missing skill request with description.
- Human approves/rejects the request first.
- On approval, workflow can auto-implement the skill pack and bind it to agent registry.

This is intentionally lightweight and auditable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REQUEST_ROOT = REPO_ROOT / "aims_workspace" / "agent_self_learning" / "skill_requests"
REQUESTS_JSONL = REQUEST_ROOT / "skill_requests.jsonl"
EVENTS_JSONL = REQUEST_ROOT / "skill_request_events.jsonl"
IMPLEMENTED_JSONL = REQUEST_ROOT / "implemented_skills.jsonl"
SKILL_PACK_DIR = REPO_ROOT / "docs" / "agents" / "skills" / "generated"
AGENT_REGISTRY = REPO_ROOT / "ops" / "agents" / "agent_skill_registry.yaml"

VALID_AGENTS = {
    "logi", "axi", "architect", "security", "poli", "qa-agent", "release-agent",
    "argus", "watchdog-agent", "traini", "doci", "docs-agent", "omi", "knomi",
    "repairman", "control-plane", "scheduler",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "skill"


def _ensure_dirs() -> None:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    SKILL_PACK_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: pathlib.Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return rows


def _load_registry() -> dict[str, Any]:
    if not AGENT_REGISTRY.exists():
        raise FileNotFoundError(f"Registry not found: {AGENT_REGISTRY}")
    data = yaml.safe_load(AGENT_REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "agents" not in data:
        raise ValueError("Invalid agent skill registry structure")
    return data


def _save_registry(data: dict[str, Any]) -> None:
    AGENT_REGISTRY.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _next_request_id(agent: str, skill_name: str) -> str:
    return f"SR-{agent.upper()}-{_slug(skill_name).upper()}-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"


def propose(agent: str, skill_name: str, description: str, task_context: str) -> dict[str, Any]:
    if agent not in VALID_AGENTS:
        raise ValueError(f"Unknown/unsupported agent '{agent}' for this workflow")

    request_id = _next_request_id(agent, skill_name)
    record = {
        "request_id": request_id,
        "created_at": _now(),
        "status": "PENDING_APPROVAL",
        "agent": agent,
        "skill_name": skill_name,
        "skill_slug": _slug(skill_name),
        "description": description,
        "task_context": task_context,
        "requested_action": "create_skill_pack_and_bind_to_agent",
        "approval_required": True,
        "approved_by": None,
        "approved_at": None,
        "implemented": False,
        "implemented_at": None,
        "generated_skill_pack": None,
        "registry_updated": False,
    }

    _append_jsonl(REQUESTS_JSONL, record)
    _append_jsonl(EVENTS_JSONL, {
        "at": _now(),
        "event": "REQUEST_CREATED",
        "request_id": request_id,
        "agent": agent,
    })
    return record


def _latest_request(request_id: str) -> dict[str, Any] | None:
    rows = _read_jsonl(REQUESTS_JSONL)
    for row in reversed(rows):
        if row.get("request_id") == request_id:
            return row
    return None


def _rewrite_request_with_update(request_id: str, updater: dict[str, Any]) -> dict[str, Any]:
    rows = _read_jsonl(REQUESTS_JSONL)
    updated_row: dict[str, Any] | None = None
    for i in range(len(rows) - 1, -1, -1):
        if rows[i].get("request_id") == request_id:
            rows[i] = {**rows[i], **updater}
            updated_row = rows[i]
            break
    if updated_row is None:
        raise ValueError(f"request_id not found: {request_id}")
    REQUESTS_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return updated_row


def approve(request_id: str, approver: str, decision: str) -> dict[str, Any]:
    req = _latest_request(request_id)
    if req is None:
        raise ValueError(f"Request not found: {request_id}")
    if req.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
        raise ValueError(f"Request cannot be decided from status={req.get('status')}")

    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decision must be APPROVED or REJECTED")

    updated = _rewrite_request_with_update(
        request_id,
        {
            "status": decision,
            "approved_by": approver,
            "approved_at": _now(),
        },
    )
    _append_jsonl(EVENTS_JSONL, {
        "at": _now(),
        "event": f"REQUEST_{decision}",
        "request_id": request_id,
        "approver": approver,
    })
    return updated


def _generate_skill_pack_markdown(req: dict[str, Any]) -> str:
    return "\n".join([
        f"# Skill: {req['skill_name']}",
        "",
        "## Purpose",
        req["description"],
        "",
        "## Trigger",
        f"Agent `{req['agent']}` identified missing capability for: {req.get('task_context', '')}",
        "",
        "## Inputs",
        "- User task context",
        "- Current system constraints",
        "- Existing registries/policies",
        "",
        "## Output Contract",
        "- Produce structured result",
        "- Include validation evidence",
        "- No secrets exposure",
        "- No destructive/runtime-unsafe actions",
        "",
        "## Safety",
        "- Human approval required before this pack is created and bound",
        "- Runtime activation/promotion still follows existing AIMS gates",
        "",
        "## Model Slot Guidance",
        "- slot14: chat/document routine behavior",
        "- slot32: engineering/reasoning/repair",
        "- slot120: heavy audit/review on demand",
        "",
    ]) + "\n"


def _bind_skill_pack_to_agent(agent: str, pack_path: str, dry_run: bool) -> tuple[bool, str]:
    registry = _load_registry()
    agents = registry.get("agents", {})
    if agent not in agents:
        return False, f"agent '{agent}' missing in registry"

    node = agents.get(agent) or {}
    packs = node.get("skill_packs")
    if not isinstance(packs, list):
        packs = []
        node["skill_packs"] = packs

    if pack_path in packs:
        return False, "already_bound"

    packs.append(pack_path)
    agents[agent] = node
    registry["agents"] = agents

    if not dry_run:
        _save_registry(registry)
    return True, "bound"


def auto_implement(request_id: str, dry_run: bool = False) -> dict[str, Any]:
    req = _latest_request(request_id)
    if req is None:
        raise ValueError(f"Request not found: {request_id}")
    if req.get("status") != "APPROVED":
        raise ValueError(f"Request must be APPROVED before implementation (status={req.get('status')})")
    if req.get("implemented") is True:
        return {"request_id": request_id, "status": "ALREADY_IMPLEMENTED"}

    slug = req.get("skill_slug") or _slug(str(req.get("skill_name", "skill")))
    skill_rel = f"docs/agents/skills/generated/{slug}.md"
    skill_abs = REPO_ROOT / skill_rel
    content = _generate_skill_pack_markdown(req)

    skill_written = False
    registry_updated = False
    bind_note = "not_attempted"

    if not dry_run:
        SKILL_PACK_DIR.mkdir(parents=True, exist_ok=True)
        skill_abs.write_text(content, encoding="utf-8")
        skill_written = True
    else:
        skill_written = True

    updated, bind_note = _bind_skill_pack_to_agent(str(req["agent"]), skill_rel, dry_run=dry_run)
    registry_updated = updated or bind_note == "already_bound"

    result = {
        "request_id": request_id,
        "implemented": True,
        "implemented_at": _now(),
        "generated_skill_pack": skill_rel,
        "registry_updated": registry_updated,
        "bind_note": bind_note,
        "dry_run": dry_run,
    }

    if not dry_run:
        _rewrite_request_with_update(request_id, result)
        _append_jsonl(IMPLEMENTED_JSONL, {**result, "at": _now()})
        _append_jsonl(EVENTS_JSONL, {
            "at": _now(),
            "event": "REQUEST_IMPLEMENTED",
            "request_id": request_id,
            "skill_pack": skill_rel,
            "registry_updated": registry_updated,
        })
    return result


def list_requests(status: str | None = None) -> list[dict[str, Any]]:
    rows = _read_jsonl(REQUESTS_JSONL)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def auto_apply_approved_pending(dry_run: bool = False) -> dict[str, Any]:
    rows = _read_jsonl(REQUESTS_JSONL)
    targets = [
        r for r in rows
        if r.get("status") == "APPROVED" and r.get("implemented") is not True
    ]
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for req in targets:
        rid = str(req.get("request_id", ""))
        if not rid:
            skipped.append({"request_id": None, "reason": "missing_request_id"})
            continue
        try:
            applied.append(auto_implement(rid, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001
            skipped.append({"request_id": rid, "reason": str(exc)})
    return {
        "approved_pending_found": len(targets),
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def main() -> int:
    _ensure_dirs()
    parser = argparse.ArgumentParser(description="AIMS skill request -> approval -> auto-implementation workflow")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_propose = sub.add_parser("propose")
    p_propose.add_argument("--agent", required=True)
    p_propose.add_argument("--skill-name", required=True)
    p_propose.add_argument("--description", required=True)
    p_propose.add_argument("--task-context", default="")

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--request-id", required=True)
    p_approve.add_argument("--approver", required=True)
    p_approve.add_argument("--decision", choices=["APPROVED", "REJECTED"], required=True)
    p_approve.add_argument("--no-auto-implement", action="store_true")
    p_approve.add_argument("--dry-run", action="store_true")

    p_impl = sub.add_parser("implement")
    p_impl.add_argument("--request-id", required=True)
    p_impl.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default=None)

    p_auto = sub.add_parser("auto-apply-approved")
    p_auto.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "propose":
        rec = propose(args.agent, args.skill_name, args.description, args.task_context)
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "approve":
        rec = approve(args.request_id, args.approver, args.decision)
        out: dict[str, Any] = {"approval": rec}
        if args.decision == "APPROVED" and not args.no_auto_implement:
            out["implementation"] = auto_implement(args.request_id, dry_run=args.dry_run)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "implement":
        print(json.dumps(auto_implement(args.request_id, dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "list":
        print(json.dumps(list_requests(args.status), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "auto-apply-approved":
        print(json.dumps(auto_apply_approved_pending(dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
