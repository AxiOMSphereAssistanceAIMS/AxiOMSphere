#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


DEFAULT_REGISTRY = "ops/agents/agent_skill_registry.yaml"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMPORTED_EXPORT_ROOT = REPO_ROOT / "aims_workspace" / "skill_exports" / "claude_plugins"
DEFAULT_DOCGEN_SKILL_OVERLAY = REPO_ROOT / "aims_workspace" / "self_learning" / "docgen_skill_registry_overlay.json"


def _resolve_candidate_path(raw: str) -> Path:
    p = Path(raw)
    if p.exists():
        return p
    # Resolve relative paths from repo root for container/runtime compatibility.
    rp = (REPO_ROOT / raw).resolve()
    if rp.exists():
        return rp
    # Common runtime mount layout fallback.
    if raw.startswith("ops/"):
        p_ops = Path("/ops") / raw[len("ops/"):]
        if p_ops.exists():
            return p_ops
    if raw.startswith("aims_workspace/"):
        p_data = Path("/data") / raw[len("aims_workspace/"):]
        if p_data.exists():
            return p_data
    return p


def _resolve_latest_export_root(base: Path = DEFAULT_IMPORTED_EXPORT_ROOT) -> Path | None:
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir() and p.name[:8].isdigit() and "_" in p.name]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def _load_imported_agent_pack_text(agent_name: str, export_root: str | None = None) -> tuple[str, Path | None]:
    """
    Load the latest exported imported-skill pack for an agent, if present.

    The exporter writes one Markdown pack per agent under:
        aims_workspace/skill_exports/claude_plugins/<timestamp>/agent_packs/<agent>.md
    """
    root = Path(export_root) if export_root else _resolve_latest_export_root()
    if root is None:
        return "", None
    pack = root / "agent_packs" / f"{agent_name}.md"
    if not pack.exists():
        return "", None
    return pack.read_text(encoding="utf-8", errors="replace"), pack


def _load_json_overlay(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _path_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _merge_unique_list(base: list[Any], overlay: list[Any]) -> list[Any]:
    merged = list(base)
    seen: set[str] = set()
    for item in merged:
        try:
            seen.add(json.dumps(item, sort_keys=True, ensure_ascii=False))
        except TypeError:
            seen.add(repr(item))
    for item in overlay:
        try:
            token = json.dumps(item, sort_keys=True, ensure_ascii=False)
        except TypeError:
            token = repr(item)
        if token in seen:
            continue
        seen.add(token)
        merged.append(item)
    return merged


def _merge_overlay_registry(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    agents = overlay.get("agents")
    if not isinstance(agents, dict):
        return base
    base_agents = base.setdefault("agents", {})
    for agent_name, overlay_agent in agents.items():
        if not isinstance(overlay_agent, dict):
            continue
        agent_entry = base_agents.setdefault(agent_name, {})
        for key, value in overlay_agent.items():
            if key == "doc_skills" and isinstance(value, dict):
                base_doc = agent_entry.setdefault("doc_skills", {})
                if isinstance(base_doc, dict):
                    skills = base_doc.setdefault("skills", [])
                    if isinstance(skills, list) and isinstance(value.get("skills"), list):
                        base_doc["skills"] = _merge_unique_list(skills, value.get("skills", []))
                    for sub_key, sub_value in value.items():
                        if sub_key == "skills":
                            continue
                        base_doc[sub_key] = sub_value
                else:
                    agent_entry["doc_skills"] = value
            elif key == "registered_skills" and isinstance(value, list):
                existing = agent_entry.get("registered_skills", [])
                if not isinstance(existing, list):
                    existing = []
                merged = _merge_unique_list(existing, value)
                agent_entry["registered_skills"] = merged
            elif key == "skill_packs" and isinstance(value, list):
                existing = agent_entry.get("skill_packs", [])
                if not isinstance(existing, list):
                    existing = []
                agent_entry["skill_packs"] = _merge_unique_list(existing, value)
            else:
                agent_entry[key] = value
    return base


@lru_cache(maxsize=16)
def _load_registry_cached(
    registry_path: str,
    registry_mtime_ns: int,
    overlay_path: str,
    overlay_mtime_ns: int,
) -> dict[str, Any]:
    p = _resolve_candidate_path(registry_path)
    if not p.exists():
        raise FileNotFoundError(f"Registry file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError(f"Registry file is not a dict: {p}")
    if "agents" not in data or not isinstance(data["agents"], dict):
        raise ValueError(f"Registry missing 'agents' map: {p}")
    overlay = _load_json_overlay(Path(overlay_path))
    if overlay:
        data = _merge_overlay_registry(data, overlay)
    return data


def load_registry(path: str = DEFAULT_REGISTRY) -> dict[str, Any]:
    overlay_path = Path(os.environ.get("AIMS_DOCGEN_SKILL_REGISTRY_OVERLAY", str(DEFAULT_DOCGEN_SKILL_OVERLAY)))
    p = _resolve_candidate_path(path)
    return _load_registry_cached(
        str(p),
        _path_mtime_ns(p),
        str(overlay_path),
        _path_mtime_ns(overlay_path),
    )


def get_agent_skill_packs(agent_name: str, registry_path: str = DEFAULT_REGISTRY) -> list[str]:
    reg = load_registry(registry_path)
    agents = reg["agents"]
    if agent_name not in agents:
        raise KeyError(f"Agent not found in registry: {agent_name}")
    global_packs = reg.get("global_skill_packs", [])
    if not isinstance(global_packs, list):
        raise ValueError("Registry global_skill_packs must be list")
    packs = agents[agent_name].get("skill_packs", [])
    if not isinstance(packs, list):
        raise ValueError(f"Agent skill_packs must be list: {agent_name}")
    return [str(x) for x in _merge_unique_list(global_packs, packs)]


def get_agent_skill_access_profile(
    agent_name: str,
    registry_path: str = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    reg = load_registry(registry_path)
    agents = reg["agents"]
    if agent_name not in agents:
        raise KeyError(f"Agent not found in registry: {agent_name}")
    agent = agents[agent_name]
    doc_skills = agent.get("doc_skills", {})
    registered_skills = agent.get("registered_skills", [])
    return {
        "agent_name": agent_name,
        "skill_packs": get_agent_skill_packs(agent_name, registry_path=registry_path),
        "doc_skills": doc_skills if isinstance(doc_skills, dict) else {},
        "registered_skills": registered_skills if isinstance(registered_skills, list) else [],
        "source_fullstack_skills": [str(x) for x in agent.get("source_fullstack_skills", []) if str(x)],
        "skill_count": len(get_agent_skill_packs(agent_name, registry_path=registry_path))
        + len(agent.get("source_fullstack_skills", [])),
    }


def load_agent_skill_text(agent_name: str, registry_path: str = DEFAULT_REGISTRY) -> str:
    packs = get_agent_skill_packs(agent_name, registry_path=registry_path)
    if not packs:
        raise ValueError(f"No skill packs defined for agent: {agent_name}")

    chunks: list[str] = []
    missing: list[str] = []
    for pack in packs:
        p = _resolve_candidate_path(pack)
        if not p.exists():
            missing.append(str(p))
            continue
        chunks.append(f"# Skill Pack: {pack}\n")
        chunks.append(p.read_text(encoding="utf-8", errors="replace").strip())
        chunks.append("")
    if not chunks:
        raise FileNotFoundError(
            f"Skill packs missing for agent '{agent_name}': {', '.join(missing) if missing else 'none loaded'}"
        )
    if missing:
        chunks.append("# Missing Skill Packs")
        for m in missing:
            chunks.append(f"- {m}")
        chunks.append("")

    imported_root = os.environ.get("AIMS_IMPORTED_CLAUDE_PLUGIN_SKILL_EXPORT_ROOT")
    imported_text, imported_pack = _load_imported_agent_pack_text(agent_name, export_root=imported_root)
    if imported_text:
        chunks.append(f"# Imported Claude Plugin Skill Pack: {imported_pack}\n")
        chunks.append(imported_text.strip())
        chunks.append("")
    return "\n".join(chunks).strip() + "\n"


def get_agent_doc_skills(agent_name: str, registry_path: str = DEFAULT_REGISTRY) -> dict[str, Any]:
    """Return the doc_skills section for an agent, or {} if not configured."""
    reg = load_registry(registry_path)
    agents = reg["agents"]
    if agent_name not in agents:
        raise KeyError(f"Agent not found in registry: {agent_name}")
    return agents[agent_name].get("doc_skills", {})


def build_doc_skill_runner(agent_name: str, registry_path: str = DEFAULT_REGISTRY):
    """
    Instantiate a DocSkillRunner scoped to the skills listed for this agent.

    Returns a DocSkillRunner instance pre-filtered to the agent's allowed skills,
    or None if the agent has no doc_skills configured.

    Usage in agent code:
        from agents.agent_skill_loader import build_doc_skill_runner
        runner = build_doc_skill_runner("doci")
        if runner:
            result = runner.invoke("doc-generate", topic="Инструкция по ТБ")
    """
    ds = get_agent_doc_skills(agent_name, registry_path=registry_path)
    if not ds:
        return None

    _ops = str(REPO_ROOT / "ops")
    if _ops not in __import__("sys").path:
        __import__("sys").path.insert(0, _ops)

    from docagent.doc_skills import DocSkillRunner, _SKILL_MAP  # type: ignore

    allowed: list[str] = ds.get("skills", list(_SKILL_MAP.keys()))

    class _ScopedRunner(DocSkillRunner):
        def invoke(self, skill: str, **kwargs: Any) -> dict:  # type: ignore[override]
            if skill not in allowed:
                return {
                    "skill": skill,
                    "status": "forbidden",
                    "notes": f"Agent '{agent_name}' is not allowed to use '{skill}'. "
                             f"Allowed: {allowed}",
                }
            return super().invoke(skill, **kwargs)

    return _ScopedRunner()


def print_agent_skill_summary(agent_name: str, registry_path: str = DEFAULT_REGISTRY) -> None:
    reg = load_registry(registry_path)
    packs = get_agent_skill_packs(agent_name, registry_path=registry_path)
    skills = reg["agents"][agent_name].get("source_fullstack_skills", [])
    doc_skills = get_agent_doc_skills(agent_name, registry_path=registry_path)
    imported_text, imported_pack = _load_imported_agent_pack_text(agent_name, export_root=os.environ.get("AIMS_IMPORTED_CLAUDE_PLUGIN_SKILL_EXPORT_ROOT"))
    print(f"agent: {agent_name}")
    print(f"skill_packs: {len(packs)}")
    for p in packs:
        print(f"- {p}")
    print(f"source_fullstack_skills: {len(skills)}")
    for s in skills:
        print(f"- {s}")
    if doc_skills:
        allowed = doc_skills.get("skills", [])
        print(f"doc_skills: {len(allowed)}")
        for s in allowed:
            print(f"- {s}")
    if imported_pack:
        print(f"imported_skill_pack: {imported_pack}")
        print(f"imported_skill_pack_chars: {len(imported_text)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load/read AIMS agent skill packs from registry.")
    parser.add_argument("--agent", required=True, help="Agent name from registry.")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY, help="Path to agent skill registry YAML.")
    parser.add_argument("--text", action="store_true", help="Print full skill pack text.")
    parser.add_argument("--doc-skills", action="store_true", help="Print doc_skills config for this agent.")
    args = parser.parse_args()

    if args.text:
        print(load_agent_skill_text(args.agent, registry_path=args.registry))
    elif args.doc_skills:
        import json
        ds = get_agent_doc_skills(args.agent, registry_path=args.registry)
        print(json.dumps(ds, indent=2))
    else:
        print_agent_skill_summary(args.agent, registry_path=args.registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
