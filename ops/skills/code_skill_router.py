#!/usr/bin/env python3
"""Route a skill name, command, or task description to the correct AIMS code skill."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "ops/skills/code_skill_registry.yaml"
BRIDGE_CFG_PATH = ROOT / "ops/gstack/claude_code_bridge/claude_code_bridge_config.yaml"

# Keyword → skill name mapping for free-text task routing.
KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["search", "find", "where", "grep", "symbol", "call graph", "import", "who calls"], "code_search"),
    (["review", "quality", "antipattern", "coupling", "smell", "lint"], "code_review"),
    (["fix", "bug", "traceback", "error", "exception", "broken", "fail", "patch"], "code_fix"),
    (["test", "coverage", "pytest", "generate test", "unit test"], "code_test"),
    (["debug", "hung", "hang", "stuck", "port", "process", "pid", "zombie"], "code_debug"),
    (["security", "secret", "injection", "owasp", "credential", "token leak"], "code_audit"),
    (["refactor", "rename", "extract", "split", "decouple", "simplify code"], "code_refactor"),
    (["perf", "performance", "vram", "gpu", "throughput", "latency", "slow", "bottleneck"], "code_perf"),
    (["slot", "model slot", "routing audit", "model registry", "resolve_slot"], "code_model_slot"),
    (["ft", "fine-tun", "train", "qlora", "training pipeline", "dataset", "eval", "adapter"], "code_ft_pipeline"),
    (["deploy", "docker", "smoke", "health", "restart", "container", "up"], "code_deploy"),
    (["scaffold", "new agent", "new worker", "new test", "template", "boilerplate"], "code_scaffold"),
    (["migrat", "schema", "alter table", "db change", "backup rollback", "sqlite"], "code_migrate"),
]

SLOT_MODEL_HINTS: dict[str, str] = {
    "32": "qwen3:32b-q8_0 (axi_omi_sphere:latest) — or qwen3-coder:30b if promoted",
    "120": "nemotron-3-super:120b",
}


def load_registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def load_bridge_cfg() -> dict[str, Any]:
    if BRIDGE_CFG_PATH.exists():
        return yaml.safe_load(BRIDGE_CFG_PATH.read_text(encoding="utf-8")) or {}
    return {}


def resolve_by_name(name: str, skills: dict[str, Any]) -> str | None:
    name_norm = name.lower().replace("-", "_").replace("/code_", "").replace("/code-", "")
    for k in skills:
        if k == name_norm or k.replace("_", "") == name_norm.replace("_", ""):
            return k
    return None


def resolve_by_command(command: str, skills: dict[str, Any]) -> str | None:
    for k, v in skills.items():
        if v.get("command", "").lstrip("/") == command.lstrip("/"):
            return k
    return None


def resolve_by_task(task: str, skills: dict[str, Any]) -> str | None:
    task_l = task.lower()
    for keywords, skill_name in KEYWORD_MAP:
        if any(kw in task_l for kw in keywords):
            if skill_name in skills:
                return skill_name
    return None


def build_route(skill_name: str, skill: dict[str, Any], bridge_cfg: dict[str, Any]) -> dict[str, Any]:
    slot = str(skill.get("slot", "32"))
    forbidden = bridge_cfg.get("global_forbidden_actions", [])
    pipeline_map = {
        "repair_learning_cycle": "slot32_training",
        "claude_code_bridge": "slot32_training" if slot == "32" else "slot120_document_learning",
    }
    owner_pipelines = skill.get("owner_pipeline", [])
    target_pipeline = None
    for op in owner_pipelines:
        if op in pipeline_map:
            target_pipeline = pipeline_map[op]
            break

    return {
        "skill": skill_name,
        "command": skill.get("command"),
        "slot": slot,
        "model_hint": SLOT_MODEL_HINTS.get(slot, "unknown"),
        "role": skill.get("role"),
        "safety_level": skill.get("safety_level"),
        "requires_validation": skill.get("requires_validation", False),
        "owner_pipeline": owner_pipelines,
        "target_pipeline": target_pipeline,
        "output_contract": skill.get("output_contract"),
        "execution_note": skill.get("execution_note"),
        "forbidden_actions": forbidden,
        "training_destination": (
            "ops/learning/events/coding/code_skills_curriculum.jsonl"
            if slot == "32"
            else "ops/learning/events/document/code_skills_document_architecture.jsonl"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Route an AIMS code skill to slot/model/pipeline")
    ap.add_argument("--skill", help="Skill name (e.g. code_fix)")
    ap.add_argument("--command", help="Skill command (e.g. /code-fix)")
    ap.add_argument("--task", help="Free-text task description")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if not any([args.skill, args.command, args.task]):
        ap.print_help()
        return 1

    reg = load_registry()
    bridge_cfg = load_bridge_cfg()
    skills = reg.get("skills", {})

    skill_name: str | None = None
    if args.skill:
        skill_name = resolve_by_name(args.skill, skills)
    elif args.command:
        skill_name = resolve_by_command(args.command, skills)
    elif args.task:
        skill_name = resolve_by_task(args.task, skills)

    if not skill_name:
        print(f"No skill matched for input: {args.skill or args.command or args.task!r}", file=sys.stderr)
        print("Available skills:", ", ".join(skills.keys()), file=sys.stderr)
        return 1

    skill = skills[skill_name]
    route = build_route(skill_name, skill, bridge_cfg)

    if args.json:
        print(json.dumps(route, indent=2, ensure_ascii=False))
    else:
        print(f"Skill:       {route['skill']}")
        print(f"Command:     {route['command']}")
        print(f"Slot:        {route['slot']}")
        print(f"Model:       {route['model_hint']}")
        print(f"Role:        {route['role']}")
        print(f"Safety:      {route['safety_level']}")
        print(f"Validation:  {route['requires_validation']}")
        print(f"Pipeline:    {route['target_pipeline']}")
        print(f"Training →   {route['training_destination']}")
        if route.get("execution_note"):
            print(f"Note:        {route['execution_note']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
