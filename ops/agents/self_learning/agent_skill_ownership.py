"""
AIMS Self-Learning — Agent Skill Ownership Map.

Defines which AIMS agent owns each skill domain.
No model calls, no I/O, no runtime side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Canonical AIMS agent identifiers (9 agents required by Phase 6 spec)
AIMS_AGENTS: tuple[str, ...] = (
    "axi",
    "omi",
    "argus",
    "logi",
    "traini",
    "knomi",
    "doci",
    "mainy_repairman",
    "hermes_external_worker",
)


@dataclass(frozen=True)
class AgentSkillOwnership:
    """Maps a hermes skill category/name to an owning AIMS agent."""

    agent_id: str
    hermes_categories: tuple[str, ...]   # hermes top-level category names
    hermes_skills: tuple[str, ...]       # specific skill names (empty = all in category)
    rationale: str

    def owns_category(self, category: str) -> bool:
        return category in self.hermes_categories

    def owns_skill(self, category: str, skill_name: str) -> bool:
        if category not in self.hermes_categories:
            return False
        if not self.hermes_skills:
            return True  # owns all skills in the category
        return skill_name in self.hermes_skills


# Master ownership map — each entry is authoritative for its domain
AGENT_SKILL_OWNERSHIP: tuple[AgentSkillOwnership, ...] = (
    AgentSkillOwnership(
        agent_id="axi",
        hermes_categories=("software-development",),
        hermes_skills=(
            "hermes-agent-skill-authoring",
            "subagent-driven-development",
            "writing-plans",
            "plan",
        ),
        rationale="Axi handles document generation planning and structured output.",
    ),
    AgentSkillOwnership(
        agent_id="omi",
        hermes_categories=("productivity",),
        hermes_skills=("ocr-and-documents",),
        rationale="Omi owns OCR and document registry operations.",
    ),
    AgentSkillOwnership(
        agent_id="argus",
        hermes_categories=("software-development",),
        hermes_skills=("systematic-debugging", "test-driven-development"),
        rationale="Argus owns diagnostics, testing, and self-healing repair loops.",
    ),
    AgentSkillOwnership(
        agent_id="logi",
        hermes_categories=("github",),
        hermes_skills=("codebase-inspection", "github-code-review", "github-pr-workflow"),
        rationale="Logi owns cross-department sync and code workflow coordination.",
    ),
    AgentSkillOwnership(
        agent_id="traini",
        hermes_categories=("mlops",),
        hermes_skills=("llama-cpp", "lm-evaluation-harness", "vllm"),
        rationale="Traini owns model training, evaluation, and inference infrastructure.",
    ),
    AgentSkillOwnership(
        agent_id="knomi",
        hermes_categories=("software-development",),
        hermes_skills=("requesting-code-review",),
        rationale="Knomi owns semantic search and knowledge retrieval workflows.",
    ),
    AgentSkillOwnership(
        agent_id="doci",
        hermes_categories=(),
        hermes_skills=(),
        rationale=(
            "Doci owns document generation sub-agent tasks; "
            "no hermes focus skills directly mapped."
        ),
    ),
    AgentSkillOwnership(
        agent_id="mainy_repairman",
        hermes_categories=(),
        hermes_skills=(),
        rationale=(
            "Mainy Repairman owns production repair execution; "
            "consumes skill plans certified by other agents."
        ),
    ),
    AgentSkillOwnership(
        agent_id="hermes_external_worker",
        hermes_categories=("dogfood",),
        hermes_skills=("",),  # category-root skill
        rationale=(
            "Hermes external worker owns the dogfood skill "
            "and meta-level skill authoring in the sandbox."
        ),
    ),
)


def resolve_owner(category: str, skill_name: str) -> str | None:
    """Return the agent_id that owns a given hermes category/skill, or None."""
    for ownership in AGENT_SKILL_OWNERSHIP:
        if ownership.owns_skill(category, skill_name):
            return ownership.agent_id
    return None


def all_agent_ids() -> list[str]:
    return list(AIMS_AGENTS)
