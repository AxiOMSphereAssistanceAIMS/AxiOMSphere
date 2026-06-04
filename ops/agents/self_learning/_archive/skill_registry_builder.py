"""
AIMS Self-Learning — Registry Builder.

Loads aims_self_learning_registry.yaml, validates all entries,
writes JSON snapshot. No model calls, no runtime side effects.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
from typing import Any

# yaml is stdlib-absent; use simple hand-rolled YAML loader for this schema
# (pyyaml may not be available in all envs; we ship a minimal parser)
try:
    import yaml as _yaml  # type: ignore[import]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_HERE = pathlib.Path(__file__).resolve().parent
_REGISTRY_YAML = _HERE / "aims_self_learning_registry.yaml"

_OUTPUT_DIR = (
    pathlib.Path(__file__).resolve().parents[3]
    / "aims_workspace" / "self_learning"
)
_JSON_SNAPSHOT = _OUTPUT_DIR / "aims_self_learning_registry_snapshot.json"
_MD_SNAPSHOT = _OUTPUT_DIR / "aims_self_learning_registry.md"

_SCHEMA_VERSION = "1.0"
_NEXT_PHASE = "AIMS_SKILL_CANDIDATE_WORKFLOW"

from .skill_registry_validator import SkillRegistryValidator, SAFETY_INVARIANTS
from .agent_skill_ownership import AIMS_AGENTS, all_agent_ids


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Registry YAML not found: {path}")
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        return _yaml.safe_load(text)
    # Minimal fallback: return raw text wrapped so smoke test can still run
    raise RuntimeError(
        "PyYAML not installed. Install with: pip install pyyaml\n"
        f"Or ensure pyyaml is available in the PYTHONPATH."
    )


def _build_md(snapshot: dict[str, Any]) -> str:
    entries = snapshot["entries"]
    by_state: dict[str, list[dict]] = {}
    for e in entries:
        by_state.setdefault(e["lifecycle_state"], []).append(e)

    lines = [
        "# AIMS Self-Learning Skill Registry",
        "",
        f"**Schema version:** `{snapshot['schema_version']}`  ",
        f"**Created:** {snapshot['created_at']}  ",
        f"**Total entries:** {snapshot['total_entries']}  ",
        f"**Next allowed phase:** `{snapshot['next_allowed_phase']}`  ",
        "",
        "## Safety Invariants",
        "",
    ]
    for k, v in snapshot["safety_invariants"].items():
        icon = "✅" if v is False else "⚠️"
        lines.append(f"- `{k}`: **{v}** {icon}")
    lines.append("")

    lines += ["## Registered Agents", ""]
    for a in snapshot["agents"]:
        lines.append(f"- `{a}`")
    lines.append("")

    lines += ["## Skill Entries by Lifecycle State", ""]
    for state in (
        "OBSERVED_PATTERN", "CANDIDATE_SKILL", "SANDBOX_SKILL",
        "CERTIFIED_SKILL", "ACTIVE_RUNTIME_SKILL", "DEPRECATED_SKILL",
    ):
        state_entries = by_state.get(state, [])
        lines.append(f"### {state} ({len(state_entries)})")
        lines.append("")
        if not state_entries:
            lines.append("_None_")
        else:
            for e in state_entries:
                model_tag = " `[MODEL]`" if e.get("risk_flags", {}).get("model_related") else ""
                lines.append(
                    f"- **{e['skill_id']}** `{e['owner_agent_id']}`{model_tag}  "
                    f"conf={e['confidence']:.2f}  obs={e['observed_count']}  "
                    f"— {e['description']}"
                )
        lines.append("")

    return "\n".join(lines) + "\n"


def build_registry_snapshot() -> dict[str, Any]:
    raw = _load_yaml(_REGISTRY_YAML)

    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    entries_raw: list[dict] = raw.get("entries", [])
    agents_in_yaml: list[str] = raw.get("agents", [])

    snapshot: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "created_at": created_at,
        "total_entries": len(entries_raw),
        "agents": agents_in_yaml,
        "entries": entries_raw,
        "safety_invariants": dict(SAFETY_INVARIANTS),
        "next_allowed_phase": _NEXT_PHASE,
    }

    validator = SkillRegistryValidator()
    is_valid = validator.validate_snapshot(snapshot)

    snapshot["validation_errors"] = validator.errors
    snapshot["validation_warnings"] = validator.warnings
    snapshot["validation_passed"] = is_valid

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _JSON_SNAPSHOT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    snapshot["report_json"] = str(_JSON_SNAPSHOT)

    _MD_SNAPSHOT.write_text(_build_md(snapshot))
    snapshot["report_md"] = str(_MD_SNAPSHOT)

    return snapshot


if __name__ == "__main__":
    result = build_registry_snapshot()
    print("=" * 60)
    print("AIMS Self-Learning Registry Snapshot")
    print("=" * 60)
    print(f"Schema version : {result['schema_version']}")
    print(f"Total entries  : {result['total_entries']}")
    print(f"Agents         : {result['agents']}")
    print(f"Valid          : {result['validation_passed']}")
    if result["validation_errors"]:
        print(f"Errors         : {result['validation_errors']}")
    if result["validation_warnings"]:
        print(f"Warnings       : {result['validation_warnings']}")
    print(f"Next phase     : {result['next_allowed_phase']}")
    print(f"JSON           : {result['report_json']}")
    print(f"MD             : {result['report_md']}")
