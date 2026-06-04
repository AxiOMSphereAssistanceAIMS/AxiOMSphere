"""Factory for GPT-assisted AIMS model data preparation artifacts.

This module enforces a three-level role contract and separate-but-connected
corpora:
- slot14: fast operational behavior and routine execution.
- slot32: engineering, reasoning, repair, and system-improvement intelligence.
- slot120: teacher/judge/document-architecture supervision material index.

It does not call training, promote models, or load slot120.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logi.model_data_quality import stable_id

ROOT = Path(__file__).resolve().parents[2]
AGENT_SKILL_REGISTRY = ROOT / "ops/agents/agent_skill_registry.yaml"


DISCOVERY_SOURCES = [
    "docs/AIMS_GSTACK_INTEGRATION_STATUS.md",
    "docs/AUTONOMY_CONTROL_PLANE_V1_CERTIFICATION.md",
    "docs/LOGI_PROCESS_INTEGRITY_ORCHESTRATOR_V1_CERTIFICATION.md",
    "docs/AUTONOMY_NEXT_STAGE_LONG_RUNNING_SELF_REGULATION.md",
    "ops/autonomy_control/README.md",
    "ops/agents/agent_skill_registry.yaml",
    "docs/agents/AIMS_GSTACK_AGENT_MAPPING.md",
    "docs/agents/skills",
    "ops/logi",
    "ops/evals",
    "aims_workspace/model_tuning_readiness/certifications/model_tuning_readiness_chain_v1_20260514_145843",
    "aims_workspace/strategic_planning/certifications",
    "aims_workspace/self_test_planning/certifications",
    "aims_workspace/traini_lifecycle/certifications",
]


SLOT14_REQUIRED = [
    "AIMS current status summary",
    "PASS/PARTIAL/FAIL explanation",
    "next safe action suggestion",
    "Telegram-style concise reporting",
    "agent routing decision",
    "user-facing clarification without over-asking",
    "document review request handling",
    "document anonymization request handling",
    "procedure update / improvement response",
    "document comparison summary",
    "template filling instruction / response",
    "routing to Omi / Doci / Knomi",
    "refusing unsafe action / not exposing secrets",
    "Russian project-management dialogue",
    "mixed Russian/English document-work dialogue",
    "routine database task execution",
    "planned database activity support",
    "database maintenance workflow guidance",
    "classify_doc / find_duplicates / reassign_doc / create_master action discipline",
    "document registry naming/classification/version signal handling",
]

SLOT32_REQUIRED = [
    "coding task implementation",
    "bash/python script repair",
    "certification report analysis",
    "JSON result interpretation",
    "evidence-chain planning",
    "contract normalization / tool mismatch detection",
    "control-plane smoke correction",
    "scheduler/watchdog implementation",
    "Logi planned action execution",
    "Traini tuning readiness decision",
    "baseline/eval/tuning/promotion safety",
    "slot32/slot120 conflict reasoning",
    "problem/corrective-action creation",
    "self-test plan generation",
    "reading artifacts and producing next action",
    "refusing false PASS or unsupported 0.98 claim",
    "repairman workflow supervision and validation",
    "multi-step technical planning and implementation sequencing",
    "dataset builder / validator / evaluator / promotion-gate repair",
    "turning model14 failures into engineering root-cause and patch cases",
    "artifact cleanup and lifecycle tooling improvements",
    "Ollama/OmniRoute/FastAPI/DB routing and reliability repair cases",
]

DISCOVERABLE_TOPICS = [
    ("Omi registry and staging workflows", "14", "high", ["ops/omi_telegram", "ops/omi_register.py"]),
    ("OCR intake and document extraction", "14", "medium", ["ops/ocr_watcher_loop.sh", "ops/omi_telegram"]),
    ("anonymization of procedures", "14", "high", ["ops/evals/autonomous_launch/phase_07_training_data.py"]),
    ("Excel/abstract template review", "14", "medium", ["aims_workspace/autonomous_tests/templates"]),
    ("document comparison and quality findings", "14", "high", ["ops/docagent", "docs/agents/skills/doci_document.md"]),
    ("Knomi search/reindex/freshness", "14", "medium", ["ops/knomi", "ops/evals/knomi_runtime_skill_smoke.py"]),
    ("Control Plane ledger interpretation", "32", "high", ["ops/autonomy_control", "ops/evals/autonomy_control_plane_certification.py"]),
    ("Logi planned action creation", "32", "high", ["ops/logi/planned_actions.py", "ops/logi/planned_action_runner.py"]),
    ("self-test planning and problem records", "32", "high", ["ops/logi/self_test_planner.py", "ops/logi/self_test_problem_manager.py"]),
    ("evidence-chain heartbeat/watchdog", "32", "high", ["ops/evals/long_running_self_regulation_certification.py"]),
    ("Traini data readiness and 0.98 target handling", "32", "high", ["ops/logi/model_tuning_readiness_chain.py"]),
    ("repairman lessons learned", "32", "medium", ["aims_workspace/repairman_memory/lessons.jsonl"]),
    ("Argus lifecycle classification", "32", "high", ["ops/evals/post_restart_service_stability_audit.py"]),
    ("Telegram delivery summaries", "14", "medium", ["ops/autonomy_control/telegram_summary.py"]),
    ("Docker/service lifecycle safety", "32", "high", ["ops/argus/service_lifecycle_policy.yaml", "docker-compose.yml"]),
    ("public README/status update tasks", "14", "low", ["docs/outreach-public/README.md"]),
]

# High-priority topics that must be present when claude_plugin_skill_adaptation
# domains are marked ACTIVE_RUNTIME in agent skill registry.
CLAUDE_DOMAIN_TOPIC_MAP = {
    "chat_and_syntax": ("chat_and_syntax", "14", "high"),
    "documents_templates_corrections": ("documents_templates_corrections", "14", "high"),
    "coding_backend_troubleshooting": ("coding_backend_troubleshooting", "32", "high"),
}

# Additional explicit tuning topics requested by current AIMS model-role guidance.
CLAUDE_DOMAIN_EXPLICIT_TOPICS = [
    ("document-work dialogue", "14", "high"),
    ("backend/debugging/script repair", "32", "high"),
    ("evidence-chain/certification tooling", "32", "high"),
]


@dataclass
class Topic:
    name: str
    slot_id: str
    priority: str
    evidence_paths: list[str]


def discover_sources() -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    for raw in DISCOVERY_SOURCES:
        path = ROOT / raw
        if path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())[:120]
            discovered.append({"path": raw, "exists": True, "type": "directory", "files_sampled": [str(p.relative_to(ROOT)) for p in files]})
        else:
            discovered.append({"path": raw, "exists": path.exists(), "type": "file", "files_sampled": [raw] if path.exists() else []})
    return discovered


def discover_topics() -> list[Topic]:
    topics: list[Topic] = []
    for name, slot, priority, paths in DISCOVERABLE_TOPICS:
        existing = [p for p in paths if (ROOT / p).exists()]
        if existing:
            topics.append(Topic(name=name, slot_id=slot, priority=priority, evidence_paths=existing))
    topics.extend(_discover_active_claude_domain_topics())
    # Deduplicate by (name, slot_id), prefer high-priority records when duplicates exist.
    dedup: dict[tuple[str, str], Topic] = {}
    priority_rank = {"high": 3, "medium": 2, "low": 1}
    for t in topics:
        key = (t.name, t.slot_id)
        if key not in dedup:
            dedup[key] = t
            continue
        prev = dedup[key]
        if priority_rank.get(t.priority, 0) > priority_rank.get(prev.priority, 0):
            dedup[key] = t
    return sorted(dedup.values(), key=lambda x: (x.slot_id, x.name.lower()))


def _discover_active_claude_domain_topics() -> list[Topic]:
    try:
        import yaml  # type: ignore
    except Exception:
        return []
    if not AGENT_SKILL_REGISTRY.exists():
        return []
    try:
        registry = yaml.safe_load(AGENT_SKILL_REGISTRY.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    adapt = registry.get("claude_plugin_skill_adaptation")
    if not isinstance(adapt, dict):
        return []
    domains = adapt.get("domains")
    if not isinstance(domains, dict):
        return []
    out: list[Topic] = []
    for domain_name, spec in domains.items():
        if not isinstance(spec, dict):
            continue
        status = str(spec.get("status", "")).strip().upper()
        if status != "ACTIVE_RUNTIME":
            continue
        mapped = CLAUDE_DOMAIN_TOPIC_MAP.get(domain_name)
        if mapped is None:
            continue
        topic_name, slot_id, priority = mapped
        out.append(
            Topic(
                name=topic_name,
                slot_id=slot_id,
                priority=priority,
                evidence_paths=["ops/agents/agent_skill_registry.yaml"],
            )
        )
    # Add explicit high-priority topic lines tied to active domains
    if any(str((domains.get("chat_and_syntax") or {}).get("status", "")).upper() == "ACTIVE_RUNTIME" for _ in [0]):
        out.append(Topic("document-work dialogue", "14", "high", ["ops/agents/agent_skill_registry.yaml"]))
    if any(str((domains.get("coding_backend_troubleshooting") or {}).get("status", "")).upper() == "ACTIVE_RUNTIME" for _ in [0]):
        out.append(Topic("backend/debugging/script repair", "32", "high", ["ops/agents/agent_skill_registry.yaml"]))
        out.append(Topic("evidence-chain/certification tooling", "32", "high", ["ops/agents/agent_skill_registry.yaml"]))
    return out


def build_slot_inventory(topics: list[Topic]) -> list[dict[str, Any]]:
    slot14_topics = SLOT14_REQUIRED + [t.name for t in topics if t.slot_id == "14"]
    slot32_topics = SLOT32_REQUIRED + [t.name for t in topics if t.slot_id == "32"]
    return [
        {
            "slot_id": "14",
            "role": "Fast operational behavior and routine execution layer for chat, document-work, routing, and database routines",
            "assigned_functions": [
                "fast/accurate intent understanding in chat and concise schema-safe responses",
                "document review, anonymization, comparison, procedure update, template filling",
                "quick document search and document-context orientation",
                "document naming/classification/versioning/registry signal handling",
                "routine database work, planned DB activities, and DB maintenance workflow support",
                "routing document tasks to Omi, Doci, and Knomi",
                "Russian/English mixed workflow dialogue",
            ],
            "source_files": [
                "docs/AIMS_GSTACK_INTEGRATION_STATUS.md",
                "ops/logi/model_level_assessor.py",
                "aims_workspace/model_tuning_readiness/certifications/model_tuning_readiness_chain_v1_20260514_145843/model_level_inventory.json",
            ],
            "evidence_paths": [t.evidence_paths[0] for t in topics if t.slot_id == "14"],
            "tuning_topics_required": sorted(set(slot14_topics)),
            "missing_from_initial_prompt": [t.name for t in topics if t.slot_id == "14" and t.name not in SLOT14_REQUIRED],
            "priority": "high",
        },
        {
            "slot_id": "32",
            "role": "Engineering intelligence layer for coding, debugging, repair, planning, testing, and system improvement",
            "assigned_functions": [
                "technical planning leadership and implementation sequencing",
                "Python/Bash/YAML/Docker/FastAPI/Ollama/OmniRoute/database coding and repair",
                "debugging, root-cause analysis, and monitoring/watchdog improvements",
                "certification/eval script creation and JSON/report interpretation",
                "evidence-chain planning and corrective-action reasoning",
                "repairman workflow supervision and validation",
                "Traini/Argus/Watchdog/model-lifecycle tooling improvements",
                "convert model14 failures into engineering repair and prevention cases",
                "resource policy and slot32/slot120 conflict decisions",
            ],
            "source_files": [
                "docs/AIMS_GSTACK_INTEGRATION_STATUS.md",
                "ops/logi/model_level_assessor.py",
                "ops/logi/model_tuning_readiness_chain.py",
            ],
            "evidence_paths": [t.evidence_paths[0] for t in topics if t.slot_id == "32"],
            "tuning_topics_required": sorted(set(slot32_topics)),
            "missing_from_initial_prompt": [t.name for t in topics if t.slot_id == "32" and t.name not in SLOT32_REQUIRED],
            "priority": "high",
        },
        {
            "slot_id": "120",
            "role": "Teacher/judge/document-architecture and quality-supervision layer (selective, high-cost)",
            "assigned_functions": [
                "candidate judging and regression detection for slot14 and slot32",
                "corrected examples, distillation tasks, DPO/preference supervision",
                "document architecture design and strict template-bound generation review",
                "document structure/completeness and client-ready quality supervision",
                "independent heavy audit when escalation criteria are met",
            ],
            "source_files": ["docs/AIMS_GSTACK_INTEGRATION_STATUS.md", "ops/logi/model_level_assessor.py"],
            "evidence_paths": ["ops/evals/dgx_model_concurrency_policy_smoke.py"],
            "tuning_topics_required": ["optional audit/eval rubric material only"],
            "missing_from_initial_prompt": [],
            "priority": "restricted",
        },
        {
            "slot_id": "cloud_teacher",
            "role": "External generator, critic, judge, and evaluator; not a local tuning target",
            "assigned_functions": ["candidate generation", "critique", "judging", "external evaluation"],
            "source_files": ["ops/nim_client.py", "ops/autonomy_control/runners.py"],
            "evidence_paths": ["ops/logi/process_integrity_orchestrator.py"],
            "tuning_topics_required": ["external evaluator route safety"],
            "missing_from_initial_prompt": [],
            "priority": "external",
        },
    ]


def build_agent_inventory() -> list[dict[str, Any]]:
    registry = ROOT / "ops/agents/agent_skill_registry.yaml"
    text = registry.read_text(encoding="utf-8") if registry.exists() else ""
    names = sorted(set(re.findall(r"^\s*([a-zA-Z0-9_-]+):\s*$", text, flags=re.MULTILINE)))
    if not names:
        names = ["axi", "logi", "omi", "doci", "knomi", "traini", "argus", "poli", "qa", "release", "security", "architect", "watchdog", "repairman"]

    role_map = {
        "axi": ("intake and routing", "14"),
        "logi": ("process integrity and planned actions", "32"),
        "omi": ("registry, staging, OCR and document memory", "14"),
        "doci": ("document generation and procedure work", "14"),
        "knomi": ("knowledge search and freshness", "14"),
        "traini": ("learning artifacts, eval and tuning readiness", "32"),
        "argus": ("runtime truth, lifecycle, models, resources", "32"),
        "poli": ("policy and approval gates", "32"),
        "qa": ("acceptance and quality validation", "32"),
        "release": ("promotion and release gates", "32"),
        "security": ("secret and safety policy", "32"),
        "architect": ("architecture and planning", "32"),
        "watchdog": ("runtime watch and heartbeat", "32"),
        "repairman": ("repair execution and lessons", "32"),
        "mainy-repair-agent": ("repair execution and lessons", "32"),
    }

    inventory: list[dict[str, Any]] = []
    for name in names:
        lowered = name.lower()
        role, slot = role_map.get(lowered, ("registered AIMS agent capability", "14/32"))
        inventory.append({
            "agent_name": name,
            "role": role,
            "functions": _agent_functions(lowered, role),
            "expected_model_slot_support": slot,
            "related_training_topics": _agent_topics(lowered),
            "source_files": ["ops/agents/agent_skill_registry.yaml", "docs/agents/skills"],
            "evidence_paths": _agent_evidence(lowered),
        })
    return inventory


def build_missing_topics_markdown(topics: list[Topic]) -> str:
    lines = [
        "# Missing Tuning Topics",
        "",
        "These topics were discovered from project files before candidate generation and added to the slot generation plans.",
        "",
        "| Topic | Slot | Priority | Evidence | Required candidate examples |",
        "|---|---:|---|---|---:|",
    ]
    for topic in topics:
        required = 8 if topic.priority == "high" else (5 if topic.priority == "medium" else 3)
        lines.append(f"| {topic.name} | {topic.slot_id} | {topic.priority} | {', '.join(topic.evidence_paths)} | {required} |")
    return "\n".join(lines) + "\n"


def build_generation_plan(slot_id: str, topics: list[Topic], updated: bool = True) -> str:
    required = SLOT14_REQUIRED if slot_id == "14" else SLOT32_REQUIRED
    discovered = [t for t in topics if t.slot_id == slot_id]
    minimum = 80 if slot_id == "14" else 60
    threshold = 0.85 if slot_id == "14" else 0.88
    lines = [
        f"# Updated Slot{slot_id} Generation Plan" if updated else f"# Slot{slot_id} Generation Plan",
        "",
        f"- minimum_candidates: `{minimum}`",
        f"- acceptance_threshold: `{threshold}`",
        "- source_context: `synthetic_from_project_profile`",
        "- status: candidate data only until QA/Traini filtering passes",
        "- forbidden_claims: no training complete, no promotion, no 0.98 achieved claim",
        "",
        "## Required Profile Topics",
    ]
    lines += [f"- {x}" for x in required]
    lines += ["", "## Discovered Project Topics Added Before Generation"]
    lines += [f"- {t.name} ({t.priority})" for t in discovered]
    return "\n".join(lines) + "\n"


def slot_profile(slot_id: str) -> dict[str, Any]:
    if slot_id == "14":
        return {
            "slot_id": "14",
            "baseline": 0.93,
            "target": 0.98,
            "gap": 0.05,
            "mode": "DATA_COLLECTION",
            "need": ">=50 accepted gold/DPO pairs",
            "role": "chat/conversational, Telegram-style responses, document-work assistant, Omi/Doci/Knomi routing",
        }
    return {
        "slot_id": "32",
        "baseline": 0.80,
        "target": 0.98,
        "gap": 0.18,
        "mode": "DATA_COLLECTION",
        "need": "dedicated AIMS coding/reasoning/eval dataset",
        "role": "coding, reasoning, repair planning, eval/certification, scheduler/watchdog/control-plane logic",
    }


def generate_slot14_candidates(topics: list[str], total: int = 90) -> list[dict[str, Any]]:
    categories = SLOT14_REQUIRED + topics
    records: list[dict[str, Any]] = []
    languages = ["ru", "en", "mixed"]
    for i in range(total):
        category = categories[i % len(categories)]
        lang = languages[i % len(languages)]
        prompt = _slot14_prompt(category, lang, i)
        ideal = _slot14_ideal(category, lang)
        rid = stable_id("s14", f"{category}:{i}:{prompt}")
        record = {
            "pair_id": rid,
            "slot_id": 14,
            "sequence": i,
            "category": category,
            "user_prompt": prompt,
            "ideal_response": ideal,
            "rejected_response": _slot14_rejected(category) if i % 3 == 0 else "",
            "why_ideal_is_better": "It stays concise, asks only necessary clarifying questions, cites evidence needs, and does not invent execution results.",
            "expected_agent_route": _slot14_route(category),
            "document_task_type": _document_task_type(category),
            "safety_notes": "Do not expose secrets, do not claim execution without evidence, preserve PASS/PARTIAL/WARN distinctions.",
            "source_context": "synthetic_from_project_profile",
            "language": lang,
            "difficulty": ["easy", "medium", "hard"][i % 3],
            "tags": _tags(category, "slot14"),
        }
        records.append(record)
    return records


def generate_slot32_candidates(topics: list[str], total: int = 72) -> list[dict[str, Any]]:
    categories = SLOT32_REQUIRED + topics
    records: list[dict[str, Any]] = []
    for i in range(total):
        category = categories[i % len(categories)]
        rid = stable_id("s32", f"{category}:{i}")
        record = {
            "task_id": rid,
            "slot_id": 32,
            "sequence": i,
            "category": category,
            "input_context": f"AIMS evidence-chain task involving {category}. Existing policy forbids slot32/slot120 concurrency and requires artifacts before PASS.",
            "user_request": _slot32_request(category, i),
            "expected_reasoning_summary": "Inspect evidence first, identify blocker or gap, make a narrow change or planned action, then validate with py_compile/audits where applicable.",
            "expected_output": _slot32_output(category),
            "validation_criteria": [
                "writes or references required evidence artifacts",
                "does not start heavy training or promotion",
                "keeps slot32/slot120 conflict false",
                "reports PASS only with validation evidence",
            ],
            "rejected_or_bad_output": "Marked PASS without reading artifacts, skipped validation, and claimed model improvement without eval evidence." if i % 4 == 0 else "",
            "why_expected_is_better": "It preserves the certified evidence chain and creates auditable next actions instead of unsupported closure.",
            "safety_constraints": [
                "no secrets",
                "no rm -rf",
                "no sudo",
                "no forced slot120 load",
                "no heavy training during certification",
            ],
            "source_context": "synthetic_from_project_profile",
            "difficulty": ["medium", "hard", "expert"][i % 3],
            "tags": _tags(category, "slot32"),
        }
        records.append(record)
    return records


def _agent_functions(name: str, role: str) -> list[str]:
    base = [role]
    if "logi" in name:
        base += ["plan -> dispatch -> collect -> compare -> correct -> validate -> report"]
    if "argus" in name or "watchdog" in name:
        base += ["runtime truth", "lifecycle observations", "model/resource policy"]
    if "traini" in name:
        base += ["dataset snapshots", "tuning readiness", "0.98 target planning"]
    if "omi" in name:
        base += ["registry", "OCR intake", "document staging"]
    if "knomi" in name:
        base += ["search relevance", "index freshness"]
    return base


def _agent_topics(name: str) -> list[str]:
    return [t.name for t in discover_topics() if name.split("-")[0] in " ".join(t.evidence_paths).lower()] or ["agent role behavior"]


def _agent_evidence(name: str) -> list[str]:
    candidates = [
        f"docs/agents/skills/{name}_*.md",
        f"ops/evals/{name}_runtime_skill_smoke.py",
        f"ops/agents/{name}_agent.py",
    ]
    return candidates


def _slot14_prompt(category: str, lang: str, i: int) -> str:
    if lang == "ru":
        return f"Дай краткий статус по теме `{category}` и следующий безопасный шаг. Не меняй файлы. #{i}"
    if lang == "mixed":
        return f"Проверь AIMS workflow for `{category}` and prepare Telegram-style summary with evidence gaps. #{i}"
    return f"Summarize AIMS status for `{category}` and route the next document-work action safely. #{i}"


def _slot14_ideal(category: str, lang: str) -> str:
    if lang == "ru":
        return f"Статус по `{category}` нужно давать только по артефактам. Если доказательств нет, отметь GAP/PARTIAL и предложи безопасную проверку без раскрытия секретов."
    if lang == "mixed":
        return f"For `{category}`, report PASS/WARN/PARTIAL from evidence, keep the Telegram summary concise, and route document or knowledge work to Omi/Doci/Knomi when relevant."
    return f"For `{category}`, state the evidence-backed status, avoid unsupported PASS claims, and propose the next safe validation or routing step."


def _slot14_rejected(category: str) -> str:
    return f"Everything for {category} is done and ready, no evidence needed."


def _slot14_route(category: str) -> str:
    text = category.lower()
    if "knomi" in text or "search" in text:
        return "Knomi"
    if "registry" in text or "ocr" in text:
        return "Omi"
    if "document" in text or "procedure" in text or "template" in text:
        return "Doci"
    return "Logi/Axi"


def _document_task_type(category: str) -> str:
    text = category.lower()
    if "anonym" in text:
        return "anonymization"
    if "comparison" in text:
        return "document_comparison"
    if "template" in text or "excel" in text:
        return "template_filling"
    if "procedure" in text:
        return "procedure_update"
    return "none"


def _slot32_request(category: str, i: int) -> str:
    return f"Implement or evaluate the `{category}` check in AIMS, write evidence, and report exact PASS/PARTIAL/FAIL status. Task #{i}"


def _slot32_output(category: str) -> str:
    return (
        f"Plan: inspect current artifacts for `{category}`, make the narrowest needed change or corrective action, "
        "write result JSON/report artifacts, run lightweight validation, and keep training/promotion blocked unless a later readiness gate approves it."
    )


def _tags(category: str, prefix: str) -> list[str]:
    return [prefix, re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_"), "evidence_chain"]
