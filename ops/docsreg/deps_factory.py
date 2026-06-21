"""
Production dependency factory for UniversalImprovementLoop.

Wraps cyclic_skills.py functions into Protocol-compliant adapters so the
universal loop runs with real services rather than mocks.

Usage:
    from ops.docsreg.deps_factory import build_production_deps
    from ops.docsreg.universal_loop.cycle import UniversalImprovementLoop

    deps = build_production_deps(archetype_type="inspection_procedure")
    loop = UniversalImprovementLoop(dependencies=deps)
    result = await loop.run(document_id, archetype_type, content)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ops.docsreg.universal_loop.context import LoopDependencies

log = logging.getLogger("deps_factory")

# SLOT32: generation + repair model (resolves via model_slots; default here is env fallback)
_SLOT32_MODEL = "axi_omi_sphere"


class OllamaDocumentGenerator:
    """Generates improved document content via SLOT32 (qwen3:32b-q8_0)."""

    def __init__(self, model: str = _SLOT32_MODEL, timeout: int = 300) -> None:
        self.model = model
        self.timeout = timeout

    async def generate(
        self, content: str, archetype_type: str, context: dict[str, Any]
    ) -> str:
        from ops.cyclic_skills import _ollama_generate  # noqa: PLC0415

        iteration = context.get("iteration_count", 1)
        failures: list[str] = context.get("failure_history", [])
        failure_hint = (
            f"\n\nPrevious validation failures to address: {', '.join(failures[-3:])}"
            if failures
            else ""
        )
        prompt = (
            f"You are an AIMS document specialist.\n"
            f"Document type: {archetype_type}  |  Iteration: {iteration}"
            f"{failure_hint}\n\n"
            f"Improve the following document to meet quality standards "
            f"(completeness ≥ 90%, no stub sections, proper structure):\n\n"
            f"{content}"
        )
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _ollama_generate(self.model, prompt, self.timeout, 3000),
        )


class StructureQualityScorer:
    """Scores document quality as float [0.0–1.0] using validate_structure()."""

    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    async def score(self, content: str, archetype_type: str) -> float:
        from ops.cyclic_skills import validate_structure  # noqa: PLC0415

        report = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: validate_structure(content, self.threshold),
        )
        return report.completeness_ratio


class ArchetypeQualityValidator:
    """Validates document structure, returning (passed, errors) tuple."""

    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    async def validate(
        self, content: str, archetype_type: str
    ) -> tuple[bool, list[str]]:
        from ops.cyclic_skills import validate_structure  # noqa: PLC0415

        report = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: validate_structure(content, self.threshold),
        )
        errors: list[str] = []
        if report.empty_sections:
            errors.append(f"Empty sections: {', '.join(report.empty_sections[:5])}")
        if report.stub_sections:
            errors.append(f"Stub sections: {', '.join(report.stub_sections[:5])}")
        if not report.passed:
            errors.append(
                f"Completeness {report.completeness_ratio:.1%} < {self.threshold:.0%}"
            )
        return report.passed, errors


class SimpleContentAuditor:
    """Lightweight content diagnostics — no LLM call, runs synchronously."""

    async def audit(self, content: str, archetype_type: str) -> dict[str, Any]:
        word_count = len(content.split())
        has_toc = any(
            marker in content
            for marker in ("Table of Contents", "## Contents", "Contents\n")
        )
        section_count = content.count("\n## ") + content.count("\n# ")
        return {
            "archetype_type": archetype_type,
            "word_count": word_count,
            "has_toc": has_toc,
            "section_count": section_count,
            "is_empty": word_count < 50,
            "likely_stub": word_count < 200,
        }


class OllamaRepairService:
    """Repairs document content via SLOT32 with failure-class-aware prompts."""

    def __init__(self, model: str = _SLOT32_MODEL, timeout: int = 300) -> None:
        self.model = model
        self.timeout = timeout

    async def repair(
        self, content: str, archetype_type: str, failure_class: str
    ) -> str:
        from ops.cyclic_skills import _ollama_generate  # noqa: PLC0415

        prompt = (
            f"You are an AIMS document repair specialist.\n"
            f"Document type: {archetype_type}  |  Failure class: {failure_class}\n\n"
            f"Repair the document to fix this failure. "
            f"Fill all stub sections, add missing content, ensure completeness ≥ 90%.\n\n"
            f"{content}"
        )
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _ollama_generate(self.model, prompt, self.timeout, 3000),
        )


def build_production_deps(archetype_type: str = "generic") -> LoopDependencies:
    """Return LoopDependencies with all real adapters wired.

    - Generator / RepairService → SLOT32 via cyclic_skills._ollama_generate()
    - Scorer / Validator       → cyclic_skills.validate_structure()
    - Auditor                  → lightweight sync diagnostics (no LLM)
    - SnapshotBuilder          → ArchetypeSnapshotBuilder (Phase 3 implementation)
    """
    from ops.docsreg.archetype_policy_adapter.snapshot_builder import (  # noqa: PLC0415
        ArchetypeSnapshotBuilder,
    )

    return LoopDependencies(
        generator=OllamaDocumentGenerator(),
        validator=ArchetypeQualityValidator(),
        scorer=StructureQualityScorer(),
        auditor=SimpleContentAuditor(),
        repair_service=OllamaRepairService(),
        snapshot_builder=ArchetypeSnapshotBuilder(),
    )
