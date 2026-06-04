#!/usr/bin/env python3
"""Imported Full Stack Skill Selector - AIMS integration layer.

This module loads the ECC source inventory generated under `aims_workspace/ecc_import/`,
augments it with the comparative analysis / skill matrix recommendations, and exposes
selectors and templates for Logi, Repairman, Traini, Claude review, and document workflows.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_ECC_ROOT = Path(__file__).resolve().parents[2] / "third_party" / "ecc"
DEFAULT_IMPORT_ROOT = Path(__file__).resolve().parents[2] / "aims_workspace" / "ecc_import"
DEFAULT_SOURCE_INVENTORY = DEFAULT_IMPORT_ROOT / "source_inventory.json"
DEFAULT_ANALYSIS_REPORT = DEFAULT_IMPORT_ROOT / "comparative_analysis_report.json"
DEFAULT_SKILL_MATRIX = DEFAULT_IMPORT_ROOT / "skill_agent_matrix.json"
DEFAULT_PHASE_SKILL_REGISTRY = Path(__file__).resolve().parents[2] / "ops" / "ecc_skills" / "phase_skill_registry.json"

MAX_LOGI_CONTEXT_SKILLS = 12
DEFAULT_SELECTION_LIMIT = 24

TARGET_ROLE_ORDER = [
    "logi",
    "repairman",
    "traini",
    "slot32_training",
    "qa",
    "release",
    "security",
    "poli",
    "argus",
    "watchdog",
    "omi",
    "knomi",
    "doci",
    "docs-agent",
    "axi",
    "qa-agent",
    "release-agent",
    "general",
]


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_phase_skill_registry() -> dict[str, Any]:
    registry = _read_json(DEFAULT_PHASE_SKILL_REGISTRY, {})
    if not isinstance(registry, dict):
        return {}
    return registry


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _repo_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip() or None
    except Exception:
        return None


def _repo_license(repo_root: Path) -> str:
    license_path = repo_root / "LICENSE"
    if not license_path.exists():
        return "unknown"
    text = _safe_read(license_path).strip()
    return next((line.strip() for line in text.splitlines() if line.strip()), "unknown")


def _short(text: str, limit: int = 220) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def _infer_category(source_type: str, name: str, description: str, source_path: str) -> str:
    text = f"{source_type} {name} {description} {source_path}".lower()
    if any(k in text for k in ["security", "secret", "pii", "phi", "privacy", "guard"]):
        return "security"
    if any(k in text for k in ["review", "audit", "verify", "qa", "checker"]):
        return "review"
    if any(k in text for k in ["release", "deploy", "ship", "publish", "rollback"]):
        return "release"
    if any(k in text for k in ["document", "doc", "ocr", "pdf", "template", "workspace"]):
        return "documents"
    if any(k in text for k in ["train", "learn", "eval", "benchmark", "lesson"]):
        return "learning"
    if any(k in text for k in ["repair", "fix", "debug", "build", "refactor"]):
        return "repair"
    if any(k in text for k in ["orchestr", "loop", "plan", "agent", "workflow", "context"]):
        return "orchestration"
    if source_type == "hook":
        return "governance"
    if source_type == "rule":
        return "policy"
    return "general"


def _infer_risk_level(text: str, source_type: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["secret", "credential", "model", "registry", "training", "external api", "aws", "production"]):
        return "high"
    if any(k in lowered for k in ["review", "qa", "release", "audit", "document", "workflow", "hook", "policy"]):
        return "medium"
    if source_type in {"hook", "rule"}:
        return "medium"
    return "low"


def _infer_aims_relevance(text: str, source_type: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["orchestr", "continuous", "agent", "review", "repair", "debug", "build", "test", "document", "knowledge", "skill", "eval", "benchmark", "security", "release", "qa", "policy"]):
        return "high"
    if source_type in {"hook", "rule"} or any(k in lowered for k in ["guide", "ops", "workflow", "pattern", "audit"]):
        return "medium"
    return "low"


def _infer_aims_target(text: str, source_type: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["document", "doc", "ocr", "template", "workspace"]):
        return "doci"
    if any(k in lowered for k in ["release", "deploy", "publish", "ship", "rollback"]):
        return "release"
    if any(k in lowered for k in ["repair", "fix", "debug", "refactor"]):
        return "repairman"
    if any(k in lowered for k in ["train", "learn", "eval", "benchmark", "lesson"]):
        return "traini"
    if any(k in lowered for k in ["security", "secret", "pii", "phi"]):
        return "security"
    if any(k in lowered for k in ["policy", "gate", "approval"]):
        return "poli"
    if any(k in lowered for k in ["knowledge", "search", "lookup"]):
        return "knomi"
    if any(k in lowered for k in ["review", "verify", "qa", "test"]):
        return "qa"
    if any(k in lowered for k in ["orchestr", "workflow", "plan", "context", "agent", "loop"]):
        return "logi"
    if source_type == "agent":
        return "general"
    return "general"


def _infer_document_relevance(text: str, source_type: str) -> tuple[str, str, str]:
    lowered = text.lower()
    if any(k in lowered for k in ["document", "doc", "ocr", "template", "archive", "intake", "registration"]):
        if any(k in lowered for k in ["compare", "review", "qa", "verify"]):
            return "high", "qa-agent", "review"
        if any(k in lowered for k in ["release", "package", "ship"]):
            return "high", "release-agent", "release"
        if any(k in lowered for k in ["archive", "register", "store", "intake"]):
            return "high", "omi", "archive_registration"
        if any(k in lowered for k in ["lookup", "search", "knowledge"]):
            return "medium", "knomi", "intake"
        if any(k in lowered for k in ["anonym", "redact", "secret", "pii", "policy"]):
            return "high", "security", "anonymization"
        return "medium", "doci", "classification"
    if source_type in {"rule", "hook"}:
        return "low", "poli", "evidence"
    return "none", "none", "none"


def _normalize_dependencies(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _build_item(
    *,
    source_type: str,
    source_path: str,
    name: str,
    description: str,
    raw_text: str,
    dependencies: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = f"{name} {description} {source_path} {raw_text}"
    doc_relevance, doc_target, doc_stage = _infer_document_relevance(text, source_type)
    item = {
        "item_id": f"{source_type}:{_slugify(name)}",
        "source_type": source_type,
        "source_path": source_path,
        "name": name,
        "description": description,
        "category": _infer_category(source_type, name, description, source_path),
        "dependencies": dependencies or [],
        "risk_level": _infer_risk_level(text, source_type),
        "aims_relevance": _infer_aims_relevance(text, source_type),
        "aims_target": _infer_aims_target(text, source_type),
        "adaptation_status": "selected",
        "reason": "",
        "document_processing_relevance": doc_relevance,
        "document_target_agent": doc_target,
        "document_workflow_stage": doc_stage,
    }
    if extra:
        item.update(extra)
    return item


def _load_source_inventory(source_root: Path) -> dict[str, Any]:
    if DEFAULT_SOURCE_INVENTORY.exists():
        inventory = _read_json(DEFAULT_SOURCE_INVENTORY, {})
        if isinstance(inventory, dict) and inventory.get("items"):
            return inventory

    # Fallback scan if the generated inventory is missing.
    items: list[dict[str, Any]] = []

    def scan_paths(source_type: str, base: Path, pattern: str) -> None:
        if not base.exists():
            return
        for path in sorted(base.rglob(pattern)):
            if path.is_dir():
                continue
            if source_type == "hook" and path.suffix.lower() != ".json":
                continue
            if source_type != "hook" and path.name.startswith("."):
                continue
            text = _safe_read(path)
            if source_type == "skill":
                name = path.parent.name
                description = next((line.strip("- ").strip() for line in text.splitlines() if line.lower().startswith("description:")), _short(_short(text, 160)))
                deps = []
            else:
                name = path.stem
                description = _short(text, 220)
                deps = []
            item = _build_item(
                source_type=source_type,
                source_path=str(path.relative_to(source_root)).replace("\\", "/"),
                name=name,
                description=description,
                raw_text=text,
                dependencies=deps,
            )
            items.append(item)

    scan_paths("skill", source_root / "skills", "SKILL.md")
    scan_paths("agent", source_root / "agents", "*.md")
    scan_paths("command", source_root / "commands", "*.md")
    scan_paths("rule", source_root / "rules", "*.md")
    scan_paths("hook", source_root / "hooks", "*.json")

    return {
        "source_repo": "https://github.com/affaan-m/ECC",
        "source_root": str(source_root),
        "source_commit": _repo_commit(source_root),
        "license": _repo_license(source_root),
        "source_urls": [
            "https://github.com/affaan-m/ECC",
            "https://github.com/affaan-m/everything-claude-code",
        ],
        "items": items,
        "profiles": [],
        "counts": {
            "skills_found": len([i for i in items if i["source_type"] == "skill"]),
            "agents_found": len([i for i in items if i["source_type"] == "agent"]),
            "commands_found": len([i for i in items if i["source_type"] == "command"]),
            "hooks_found": len([i for i in items if i["source_type"] == "hook"]),
            "rules_found": len([i for i in items if i["source_type"] == "rule"]),
        },
    }


def _load_analysis_recommendations() -> dict[str, Any]:
    report = _read_json(DEFAULT_ANALYSIS_REPORT, {})
    matrix = _read_json(DEFAULT_SKILL_MATRIX, {})
    analysis_items: list[dict[str, Any]] = []
    critical_gaps = []

    def _phase_entries(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        phase_entries: list[tuple[str, dict[str, Any]]] = []
        for phase in ("phase_1_critical", "phase_2_high", "phase_3_medium"):
            section = payload.get("recommendations", {}).get(phase, {})
            for entry in section.get("skills", []) or []:
                phase_entries.append((phase, entry))
        return phase_entries

    phase_entries = _phase_entries(report)
    if not phase_entries and isinstance(matrix.get("skills_matrix"), dict):
        for phase, entries in matrix["skills_matrix"].items():
            for skill_name, meta in entries.items():
                phase_entries.append((phase, {"skill": skill_name, **meta}))

    phase_target_map = {
        "context-compression": "logi",
        "agentic-orchestration": "logi",
        "teaching-patterns": "qa",
        "failure-triage": "repairman",
        "failure-pattern-extraction": "traini",
        "policy-gate-framework": "poli",
        "eval-fixture-generation": "traini",
        "incident-correlation": "argus",
        "semantic-search-advanced": "knomi",
    }
    doc_map = {
        "logi": ("none", "none", "none"),
        "qa": ("low", "qa-agent", "review"),
        "repairman": ("low", "none", "none"),
        "traini": ("low", "none", "none"),
        "poli": ("medium", "poli", "review"),
        "argus": ("low", "none", "none"),
        "knomi": ("medium", "knomi", "intake"),
    }

    for phase, entry in phase_entries:
        skill_name = str(entry.get("skill") or entry.get("name") or entry.get("skill_name") or "analysis-skill")
        agent = str(entry.get("agent") or phase_target_map.get(skill_name, "general"))
        target = phase_target_map.get(skill_name, agent if agent in TARGET_ROLE_ORDER else "general")
        phase_label = phase.replace("_", " ")
        doc_relevance, doc_target, doc_stage = doc_map.get(target, ("none", "none", "none"))
        description = str(entry.get("impact") or entry.get("implementation") or entry.get("value") or "")
        item = {
            "item_id": f"analysis:{phase}:{_slugify(skill_name)}",
            "source_type": "analysis_skill",
            "source_path": f"aims_workspace/ecc_import/{DEFAULT_ANALYSIS_REPORT.name}::{phase}:{skill_name}",
            "name": skill_name,
            "description": description,
            "category": "analysis",
            "dependencies": [],
            "risk_level": "medium",
            "aims_relevance": "high",
            "aims_target": target,
            "adaptation_status": "selected",
            "reason": f"Phase recommendation from ECC comparative analysis ({phase_label}).",
            "document_processing_relevance": doc_relevance,
            "document_target_agent": doc_target,
            "document_workflow_stage": doc_stage,
            "phase": phase,
            "analysis_agent": agent,
            "analysis_impact": entry.get("impact", ""),
            "analysis_effort": entry.get("effort", ""),
            "analysis_value": entry.get("value", ""),
        }
        analysis_items.append(item)

    if isinstance(report, dict):
        overall = report.get("overall_findings", {})
        critical_gaps = overall.get("top_3_gaps", []) or []
        if len(critical_gaps) < 4:
            critical_gaps.append(["document workflow mapping", "Document-processing support was not explicitly split into Doci/Docs-agent/Omi roles"])

    return {
        "report": report,
        "matrix": matrix,
        "analysis_skills": analysis_items,
        "critical_gaps": critical_gaps[:4],
        "phase_1_critical": analysis_items[:4],
        "phase_2_high": analysis_items[4:7],
        "phase_3_medium": analysis_items[7:9],
    }


def build_phase_skill_registry() -> dict[str, Any]:
    analysis = _load_analysis_recommendations()
    phases = []
    for phase_name, items in (
        ("phase_1_critical", analysis["phase_1_critical"]),
        ("phase_2_high", analysis["phase_2_high"]),
        ("phase_3_medium", analysis["phase_3_medium"]),
    ):
        phase_label = phase_name.replace("_", " ").title()
        phases.append(
            {
                "phase": phase_name,
                "label": phase_label,
                "skills": [
                    {
                        "skill_name": item["name"],
                        "analysis_item_id": item["item_id"],
                        "target_agent": item["aims_target"],
                        "document_target_agent": item["document_target_agent"],
                        "document_workflow_stage": item["document_workflow_stage"],
                        "reason": item["reason"],
                    }
                    for item in items
                ],
            }
        )

    return {
        "version": "v1",
        "source": "comparative_analysis_report + skill_agent_matrix",
        "explicit_phases": phases,
        "explicit_skill_names": [skill["skill_name"] for phase in phases for skill in phase["skills"]],
        "target_order": TARGET_ROLE_ORDER,
        "selection_policy": {
            "mode": "explicit_registry_first",
            "registry_priority": True,
            "heuristics_used_for_remainder": True,
            "max_logi_context_skills": MAX_LOGI_CONTEXT_SKILLS,
            "selection_limit": DEFAULT_SELECTION_LIMIT,
        },
    }


def load_imported_skill_inventory(source_root: str | Path | None = None) -> dict[str, Any]:
    repo_root = Path(source_root or DEFAULT_ECC_ROOT).resolve()
    if not repo_root.exists():
        raise FileNotFoundError(f"ECC source root not found: {repo_root}")

    inventory = _load_source_inventory(repo_root)
    analysis = _load_analysis_recommendations()
    items = [dict(item) for item in inventory.get("items", [])]
    items.extend(dict(item) for item in analysis["analysis_skills"])

    return {
        "source_repo": inventory.get("source_repo", "https://github.com/affaan-m/ECC"),
        "source_root": inventory.get("source_root", str(repo_root)),
        "source_commit": inventory.get("source_commit") or _repo_commit(repo_root),
        "license": inventory.get("license", _repo_license(repo_root)),
        "source_urls": inventory.get("source_urls", [
            "https://github.com/affaan-m/ECC",
            "https://github.com/affaan-m/everything-claude-code",
        ]),
        "profiles": inventory.get("profiles", []),
        "items": items,
        "counts": inventory.get("counts", {}),
        "summary": summarize_selected_skill_pack(items, total_inventory=True),
        "analysis": analysis,
        "analysis_summary": {
            "phase_1_count": len(analysis["phase_1_critical"]),
            "phase_2_count": len(analysis["phase_2_high"]),
            "phase_3_count": len(analysis["phase_3_medium"]),
            "critical_gap_count": len(analysis["critical_gaps"]),
        },
    }


def _score_item_for_task(task_text: str, item: dict[str, Any], analysis_items: set[str]) -> int:
    text = f"{task_text} {item.get('name', '')} {item.get('description', '')} {item.get('category', '')} {item.get('aims_target', '')} {item.get('document_target_agent', '')}".lower()
    score = 0

    if item.get("item_id") in analysis_items:
        score += 30

    if item.get("aims_relevance") == "high":
        score += 4
    elif item.get("aims_relevance") == "medium":
        score += 2

    if item.get("document_processing_relevance") == "high":
        score += 4
    elif item.get("document_processing_relevance") == "medium":
        score += 2
    elif item.get("document_processing_relevance") == "low":
        score += 1

    role_hits = {
        "logi": ["logi", "orchestr", "workflow", "context", "continuous", "plan"],
        "repairman": ["repair", "fix", "debug", "test", "refactor"],
        "traini": ["train", "learn", "eval", "lesson", "benchmark", "failure"],
        "qa": ["qa", "review", "verify", "check", "audit"],
        "release": ["release", "ship", "deploy", "package", "rollback"],
        "security": ["security", "secret", "redact", "pii", "policy"],
        "poli": ["policy", "gate", "approval", "guard"],
        "knomi": ["knowledge", "search", "lookup", "semantic", "context"],
        "doci": ["document", "doc", "ocr", "template", "compare", "anonym"],
        "docs-agent": ["document", "doc", "consolidat", "bundle", "package"],
        "omi": ["archive", "registration", "intake", "storage"],
        "axi": ["customer", "request", "intake", "orchestr"],
    }
    target = item.get("aims_target", "general")
    if target in role_hits and any(k in text for k in role_hits[target]):
        score += 4
    if any(k in text for k in ["document", "doc", "ocr", "template", "archive", "intake", "registration"]) and item.get("document_processing_relevance") != "none":
        score += 4
    source_type = item.get("source_type")
    if source_type == "analysis_skill":
        score += 3
    elif source_type == "skill":
        score += 5
    elif source_type == "agent":
        score += 4
    elif source_type == "command":
        score += 1
    elif source_type in {"hook", "rule"}:
        score += 1

    if source_type in {"skill", "agent"} and any(k in text for k in ["import", "full stack", "skill pack", "live cycle"]):
        score += 3
    return score


def select_skills_for_task(
    task_text: str,
    inventory: dict[str, Any] | None = None,
    max_items: int = DEFAULT_SELECTION_LIMIT,
) -> list[dict[str, Any]]:
    inventory = inventory or load_imported_skill_inventory()
    candidates = [dict(item) for item in inventory["items"] if item.get("aims_relevance") != "reject"]
    analysis_ids = {item["item_id"] for item in inventory.get("analysis", {}).get("analysis_skills", [])}
    phase_registry = _load_phase_skill_registry()
    explicit_skill_names = set(phase_registry.get("explicit_skill_names", []))
    explicit_item_ids = set(phase_registry.get("explicit_analysis_item_ids", []))
    for item in candidates:
        item["selection_score"] = _score_item_for_task(task_text, item, analysis_ids)
        if item.get("item_id") in explicit_item_ids:
            item["selection_score"] += 20
    candidates.sort(
        key=lambda item: (
            -item["selection_score"],
            TARGET_ROLE_ORDER.index(item.get("aims_target", "general")) if item.get("aims_target", "general") in TARGET_ROLE_ORDER else len(TARGET_ROLE_ORDER),
            item.get("source_type", ""),
            item.get("name", ""),
        )
    )

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    explicit_selection = [item for item in candidates if item.get("item_id") in explicit_item_ids]
    for item in explicit_selection:
        if len(selected) >= max_items:
            break
        if item["item_id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["item_id"])

    for item in candidates:
        if len(selected) >= max_items:
            break
        if item["item_id"] in selected_ids:
            continue
        if item["item_id"] in analysis_ids or item.get("document_processing_relevance") == "high":
            selected.append(item)
            selected_ids.add(item["item_id"])

    for item in candidates:
        if len(selected) >= max_items:
            break
        if item["item_id"] in selected_ids:
            continue
        if item["selection_score"] >= 5:
            selected.append(item)
            selected_ids.add(item["item_id"])

    return selected[:max_items]


def map_skill_to_aims_agent(item: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    text = f"{item.get('name', '')} {item.get('description', '')} {item.get('category', '')} {item.get('aims_target', '')} {item.get('document_target_agent', '')}".lower()
    target = item.get("aims_target", "general")
    if target and target != "general":
        roles.append(target)
    if item.get("document_processing_relevance") != "none" and item.get("document_target_agent") not in {None, "", "none"}:
        roles.append(item["document_target_agent"])
    if any(k in text for k in ["logi", "orchestr", "workflow", "plan", "context", "loop"]):
        roles.append("logi")
    if any(k in text for k in ["repair", "debug", "fix", "refactor", "test"]):
        roles.append("repairman")
    if any(k in text for k in ["train", "learn", "eval", "benchmark", "lesson"]):
        roles.append("traini")
    if any(k in text for k in ["review", "qa", "verify", "audit"]):
        roles.append("qa-agent")
    if any(k in text for k in ["release", "deploy", "publish", "rollback"]):
        roles.append("release-agent")
    if any(k in text for k in ["security", "secret", "pii", "phi"]):
        roles.append("security")
    if any(k in text for k in ["policy", "gate", "approval"]):
        roles.append("poli")
    if any(k in text for k in ["knowledge", "search", "lookup", "semantic"]):
        roles.append("knomi")
    if any(k in text for k in ["document", "doc", "ocr", "template", "archive", "intake", "registration"]):
        roles.extend(["doci", "docs-agent"])
    if any(k in text for k in ["archive", "intake", "registration", "storage"]):
        roles.append("omi")
    if any(k in text for k in ["customer", "request", "intake"]):
        roles.append("axi")
    if not roles:
        roles.append("general")
    deduped: list[str] = []
    for role in roles:
        if role not in deduped:
            deduped.append(role)
    return deduped


def build_logi_skill_context(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = selected_items[:MAX_LOGI_CONTEXT_SKILLS]
    return {
        "role": "logi",
        "selected_skill_count": len(selected_items),
        "loaded_skill_count": len(selected),
        "selected_skill_ids": [item["item_id"] for item in selected],
        "selected_skill_names": [item["name"] for item in selected],
        "target_agents": sorted({agent for item in selected for agent in map_skill_to_aims_agent(item)}),
        "context_summary": "Load a compact imported skill pack and keep the rest in the source inventory.",
        "safety_notes": [
            "task-scope execution only",
            "no mass prompt injection",
            "no external API calls",
            "no training launch",
            "final policy gate required",
        ],
        "analysis_phase_skills": [item["item_id"] for item in selected if item["source_type"] == "analysis_skill"],
        "document_bridge": [item["item_id"] for item in selected if item.get("document_processing_relevance") != "none"],
    }


def build_repairman_task_template(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    subset = [item for item in selected_items if item.get("aims_target") in {"repairman", "qa", "security", "poli", "release"}]
    return {
        "role": "repairman",
        "template_name": "imported_full_stack_repair_task",
        "objective": "Execute the concrete repair work identified by the imported skill selection and return evidence.",
        "selected_skill_ids": [item["item_id"] for item in subset[:10]],
        "inputs": {
            "task_scope_execution_allowed": True,
            "intermediate_approval_required": False,
            "final_policy_gate_required": True,
        },
        "allowed_actions": [
            "local code patches",
            "local config patches",
            "local tests and smoke runs",
            "queue processing",
            "evidence generation",
        ],
        "forbidden_actions": [
            "secrets exposure",
            "irreversible destructive actions",
            "model registry mutation",
            "training launch",
            "uncontrolled external API calls",
        ],
        "expected_outputs": [
            "repair diff",
            "verification log",
            "final gate PASS/WARN/FAIL",
        ],
    }


def build_traini_learning_material_template(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    subset = [item for item in selected_items if item.get("aims_target") in {"traini", "slot32_training", "logi", "repairman"}]
    return {
        "role": "traini",
        "template_name": "imported_full_stack_learning_material",
        "objective": "Capture reasoning, routing, and workflow mistakes as learning material without starting training.",
        "selected_skill_ids": [item["item_id"] for item in subset[:10]],
        "learning_topics": [
            "reasoning/routing mistakes",
            "task decomposition",
            "review handoff correctness",
            "repair verification gaps",
            "document processing handoff patterns",
        ],
        "required_artifacts": [
            "failure case",
            "corrected answer",
            "lesson summary",
            "no-training confirmation",
        ],
        "forbidden_actions": [
            "training launch",
            "model registry changes",
            "model promotion",
            "external API calls",
        ],
    }


def build_claude_reviewer_prompt_template(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    subset = [item for item in selected_items if item.get("aims_target") in {"qa", "release", "security", "poli", "logi"}]
    return {
        "role": "claude_code_reviewer",
        "template_name": "imported_full_stack_claude_review",
        "objective": "Review the imported skill pack, verify scope compliance, and emit a non-fake verdict.",
        "selected_skill_ids": [item["item_id"] for item in subset[:12]],
        "review_checklist": [
            "scope compliance",
            "reversibility",
            "rollback path",
            "tests passed",
            "evidence package exists",
            "no secrets exposed",
            "no external/API/AWS call outside scope",
        ],
        "allowed_actions": [
            "return verdict",
            "request repairman execution",
            "generate learning material",
            "mark final gate pending/passed/failed",
        ],
        "forbidden_actions": [
            "fake approval",
            "automatic execution after review",
            "model training launch",
            "registry mutation",
        ],
    }


def summarize_selected_skill_pack(selected_items: list[dict[str, Any]], total_inventory: bool = False) -> dict[str, Any]:
    counts = {
        "total": len(selected_items),
        "skills": sum(1 for item in selected_items if item.get("source_type") == "skill"),
        "agents": sum(1 for item in selected_items if item.get("source_type") == "agent"),
        "commands": sum(1 for item in selected_items if item.get("source_type") == "command"),
        "hooks": sum(1 for item in selected_items if item.get("source_type") == "hook"),
        "rules": sum(1 for item in selected_items if item.get("source_type") == "rule"),
        "analysis_skills": sum(1 for item in selected_items if item.get("source_type") == "analysis_skill"),
        "document_high": sum(1 for item in selected_items if item.get("document_processing_relevance") == "high"),
        "document_medium": sum(1 for item in selected_items if item.get("document_processing_relevance") == "medium"),
        "document_low": sum(1 for item in selected_items if item.get("document_processing_relevance") == "low"),
        "document_none": sum(1 for item in selected_items if item.get("document_processing_relevance") == "none"),
    }
    target_counts: dict[str, int] = {}
    for item in selected_items:
        target_counts[item.get("aims_target", "general")] = target_counts.get(item.get("aims_target", "general"), 0) + 1
    document_target_counts: dict[str, int] = {}
    for item in selected_items:
        document_target_counts[item.get("document_target_agent", "none")] = document_target_counts.get(item.get("document_target_agent", "none"), 0) + 1
    return {
        "counts": counts,
        "target_counts": dict(sorted(target_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "document_target_counts": dict(sorted(document_target_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "top_items": [item["item_id"] for item in selected_items[:10]],
        "inventory_mode": bool(total_inventory),
    }


def build_document_skill_inventory(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("document_processing_relevance") != "none"]


def build_document_workflow_role_mapping(document_items: list[dict[str, Any]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {
        "doci": [],
        "docs-agent": [],
        "omi": [],
        "axi": [],
        "qa-agent": [],
        "release-agent": [],
        "knomi": [],
        "security": [],
        "poli": [],
        "none": [],
    }
    for item in document_items:
        mapping.setdefault(item.get("document_target_agent", "none"), []).append(item["item_id"])
    return mapping


def build_document_qa_release_templates(document_items: list[dict[str, Any]]) -> dict[str, Any]:
    def ids(target: str) -> list[str]:
        return [item["item_id"] for item in document_items if item.get("document_target_agent") == target][:8]

    return {
        "doci_single_document_review": {
            "role": "doci",
            "objective": "Review a single document, identify issues, and return a corrected action list.",
            "selected_skill_ids": ids("doci"),
            "checklist": [
                "document type recognized",
                "content compared against source",
                "anonymization needs identified",
                "no hidden secret exposure",
            ],
        },
        "docs_agent_multi_document_consolidation": {
            "role": "docs-agent",
            "objective": "Consolidate multiple documents into a single release-ready package.",
            "selected_skill_ids": ids("docs-agent"),
            "checklist": [
                "inputs listed",
                "documents normalized",
                "duplicates removed",
                "release package prepared",
            ],
        },
        "omi_registration_archive_handoff": {
            "role": "omi",
            "objective": "Prepare a safe intake-to-archive handoff for registered documents.",
            "selected_skill_ids": ids("omi"),
            "checklist": [
                "intake identified",
                "OCR handoff status captured",
                "registration metadata preserved",
                "no production archive mutation outside scope",
            ],
        },
        "qa_document_review_checklist": {
            "role": "qa-agent",
            "objective": "Validate document quality, evidence completeness, and correctness.",
            "selected_skill_ids": ids("qa-agent"),
            "checklist": [
                "evidence path present",
                "quality decision justified",
                "redaction verified",
                "no secrets exposed",
            ],
        },
        "release_document_package_checklist": {
            "role": "release-agent",
            "objective": "Package a document for release with rollback and verification notes.",
            "selected_skill_ids": ids("release-agent"),
            "checklist": [
                "package contents enumerated",
                "rollback path documented",
                "release gate explicit",
                "final artifact path recorded",
            ],
        },
        "security_poli_anonymization_checklist": {
            "role": "security",
            "objective": "Anonymize or protect sensitive document data before downstream use.",
            "selected_skill_ids": ids("security") + ids("poli"),
            "checklist": [
                "sensitive data identified",
                "redaction or masking applied",
                "policy gate applied",
                "no raw secrets copied",
            ],
        },
        "knomi_document_lookup": {
            "role": "knomi",
            "objective": "Find the right document source or context before workflow execution.",
            "selected_skill_ids": ids("knomi"),
            "checklist": [
                "source path or context found",
                "lookup is read-only",
                "result can be cited",
            ],
        },
    }


def build_aims_role_skill_mapping(selected_items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = {role: [] for role in TARGET_ROLE_ORDER}
    for item in selected_items:
        for role in map_skill_to_aims_agent(item):
            mapping.setdefault(role, []).append(
                {
                    "item_id": item["item_id"],
                    "name": item["name"],
                    "source_type": item["source_type"],
                    "source_path": item["source_path"],
                    "adaptation_status": item.get("adaptation_status", "selected"),
                    "reason": item.get("reason", ""),
                }
            )
    return {role: entries for role, entries in mapping.items() if entries}


def annotate_selection_status(items: list[dict[str, Any]], adapted_ids: set[str] | None = None) -> list[dict[str, Any]]:
    adapted_ids = adapted_ids or set()
    for item in items:
        if item["item_id"] in adapted_ids:
            item["adaptation_status"] = "adapted"
            item["reason"] = "Selected and adapted into an AIMS template or role mapping."
        elif item.get("document_processing_relevance") == "high":
            item["adaptation_status"] = "selected"
            item["reason"] = "Document workflow candidate selected for AIMS adaptation."
        elif item.get("aims_relevance") == "high":
            item["adaptation_status"] = "selected"
            item["reason"] = "Selected for AIMS full-stack import adaptation."
        elif item.get("aims_relevance") == "medium":
            item["adaptation_status"] = "needs_review"
            item["reason"] = "Useful but should be reviewed before direct adaptation."
        else:
            item["adaptation_status"] = "rejected"
            item["reason"] = "Low AIMS relevance."
    return items


def build_import_pack(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    document_items = build_document_skill_inventory(selected_items)
    return {
        "import_source": "ECC",
        "source_repo": "https://github.com/affaan-m/ECC",
        "selected_items": selected_items,
        "summary": summarize_selected_skill_pack(selected_items),
        "role_mapping": build_aims_role_skill_mapping(selected_items),
        "document_workflow_mapping": build_document_workflow_role_mapping(document_items),
        "document_templates": build_document_qa_release_templates(document_items),
        "logi_context": build_logi_skill_context(selected_items),
        "repairman_template": build_repairman_task_template(selected_items),
        "traini_template": build_traini_learning_material_template(selected_items),
        "claude_reviewer_template": build_claude_reviewer_prompt_template(selected_items),
        "analysis": load_imported_skill_inventory().get("analysis", {}),
    }


class ImportedSkillSelector:
    """Convenience wrapper for smoke tests and simple consumers."""

    def __init__(self, ecc_source_path: str = str(DEFAULT_ECC_ROOT)) -> None:
        self.ecc_path = Path(ecc_source_path)
        self.inventory = load_imported_skill_inventory(self.ecc_path)

    def select_skills_for_task(self, task_type: str) -> list[str]:
        selected = select_skills_for_task(task_type, self.inventory, max_items=8)
        return [item["item_id"] for item in selected]

    def build_logi_skill_context(self) -> dict[str, Any]:
        selected = select_skills_for_task("logi orchestration review repair document", self.inventory, max_items=12)
        return build_logi_skill_context(selected)

    def build_repairman_task_template(self) -> dict[str, Any]:
        selected = select_skills_for_task("repairman debugging test repair", self.inventory, max_items=12)
        return build_repairman_task_template(selected)

    def build_traini_learning_material_template(self) -> dict[str, Any]:
        selected = select_skills_for_task("traini learning failure extraction", self.inventory, max_items=12)
        return build_traini_learning_material_template(selected)

    def build_claude_reviewer_prompt_template(self) -> dict[str, Any]:
        selected = select_skills_for_task("claude code review qa release policy", self.inventory, max_items=12)
        return build_claude_reviewer_prompt_template(selected)

    def summarize_selected_skill_pack(self) -> dict[str, Any]:
        selected = select_skills_for_task("logi repairman traini document", self.inventory, max_items=24)
        return summarize_selected_skill_pack(selected)


__all__ = [
    "ImportedSkillSelector",
    "annotate_selection_status",
    "build_aims_role_skill_mapping",
    "build_claude_reviewer_prompt_template",
    "build_document_qa_release_templates",
    "build_document_skill_inventory",
    "build_document_workflow_role_mapping",
    "build_import_pack",
    "build_logi_skill_context",
    "build_repairman_task_template",
    "build_traini_learning_material_template",
    "load_imported_skill_inventory",
    "map_skill_to_aims_agent",
    "select_skills_for_task",
    "summarize_selected_skill_pack",
]
