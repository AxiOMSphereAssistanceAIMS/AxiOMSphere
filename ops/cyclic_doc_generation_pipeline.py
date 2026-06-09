"""
Cyclic Document Generation Pipeline — Parallel Omi + Axi + Claude Code Audit

Implements three-tier parallel generation with quality validation:
1. OMI (Local): Searches internal DB → generates draft with internal standards
2. AXI (Internet): Searches external sources → validates & recommends improvements
3. CLAUDE CODE CLI (Auditor): Validates both Omi & Axi work independently

All three run in parallel. Results are merged and applied to next cycle.
Saves training pairs at each cycle for continuous fine-tuning.

Reference template: Asset Integrity Management Policy and Framework (879 pages, 10 tables)
Target: 95% match on structure, standards accuracy, section coverage

Usage:
    python ops/cyclic_doc_generation_pipeline.py \
        --topic "Asset Integrity Management Policy and Framework" \
        --reference-pdf "/media/.../Asset Integrity Management Policy and Framework_1.docx" \
        --max-cycles 5 \
        --target-quality 0.95 \
        --save-training-pairs
"""

import json
import logging
import os
import re
import subprocess
import sys
import asyncio
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

log = logging.getLogger("cyclic_doc_pipeline")

# Max sections per Bedrock audit call for chunked path.
# 14 sections × ~350 tokens/finding ≈ 4900 output tokens — well within 8000 limit.
_AUDIT_CHUNK_SIZE = 14

# Skills
from ops.cyclic_skills import (  # noqa: E402
    validate_structure,
    verify_recommendations,
    quality_gate,
    expand_stub_sections,
)
from ops.agents.skills.section_editor import (  # noqa: E402
    apply_section_edits,
    normalize_rec,
    _extract_reference_section,
)
from ops.agents.skills.context_grounded_document_generation import (  # noqa: E402
    build_generation_context,
    render_generation_prompt,
    write_context_manifest,
)
from ops.docs_pipeline.bedrock_doc_audit import (  # noqa: E402
    bedrock_doc_audit,
    bedrock_axi_validate,
    parse_json_from_response,
)
from ops.agents.skills.docsreg_phase1_convergence import (  # noqa: E402
    Phase1ConvergenceOrchestrator,
)
from ops.agents.skills.docsreg_phase2_nesting import apply_phase2_nesting  # noqa: E402
from ops.agents.skills.docsreg_phase3_content_quality import select_phase3_recommendations  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# MODEL CONFIGURATION — Route operations to optimal models
# ──────────────────────────────────────────────────────────────────────────────

class ModelConfig:
    """Model routing: assign operations to optimal slot models.

    VRAM Constraint (DGX 128GB total):
    - SLOT14 (14B) + SLOT120 (35B) = compatible (max ~45GB, very safe)
    - Pipeline uses both slots for search and reasoning operations
    - Awaiting user command to activate full dual-model processing
    """
    # Slot 14: Search operations (14B model)
    # From ops/config/model_slots.yaml - v19 benchmark winner when eval complete
    SLOT14_SEARCH = "qwen25-chat-14-v19-new:latest"

    # Slot 120: Deep reasoning & validation (35B coding/reasoning model)
    # Production benchmark winner: Qwen3.6-35B fine-tuned for reasoning
    SLOT120_REASONING = "qwen36-reasoning-35b-v1:latest"

    # Legacy aliases (for backward compatibility during transition)
    SEARCH_MODEL = SLOT14_SEARCH
    REASONING_MODEL = SLOT120_REASONING


SLOT120_NUM_CTX = int(os.environ.get("AIMS_DOC_SLOT120_NUM_CTX", "32768"))


def _claude_bedrock_env() -> dict[str, str]:
    env = os.environ.copy()
    profile = env.setdefault(
        "AWS_PROFILE",
        "AdministratorAccess-445100240501",
    )
    env.setdefault("AWS_REGION", "us-east-1")
    env.setdefault("CLAUDE_CODE_USE_BEDROCK", "1")
    env.setdefault("AIMS_CLAUDE_REVIEW_PROVIDER", "aws_bedrock_claude_code")
    env.setdefault("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.claude-sonnet-4-6")
    env.setdefault("ANTHROPIC_DEFAULT_OPUS_MODEL", "us.anthropic.claude-opus-4-6-v1")
    env.setdefault("AIMS_CLAUDE_REVIEW_HEAVY_MODEL", "opus")
    env.setdefault("AIMS_CLAUDE_REVIEW_ALLOW_OPUS", "1")

    # Claude Code's AWS SDK may ignore the AWS CLI role-credential cache and
    # try to use an expired SSO bearer token. Export the still-valid temporary
    # role credentials into the child process without logging or persisting
    # their values.
    if (
        "AWS_ACCESS_KEY_ID" not in env
        and "PYTEST_CURRENT_TEST" not in env
    ):
        try:
            exported = subprocess.run(
                [
                    "aws",
                    "configure",
                    "export-credentials",
                    "--profile",
                    profile,
                    "--format",
                    "process",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            credentials = (
                json.loads(exported.stdout)
                if exported.returncode == 0
                else None
            )
            if credentials is None:
                now = datetime.now(timezone.utc)
                cached_candidates: list[tuple[datetime, dict[str, Any]]] = []
                for cache_path in (
                    Path.home() / ".aws" / "cli" / "cache"
                ).glob("*.json"):
                    try:
                        cached = json.loads(cache_path.read_text())
                        cached_credentials = cached["Credentials"]
                        expiration = datetime.fromisoformat(
                            cached_credentials["Expiration"].replace(
                                "Z",
                                "+00:00",
                            )
                        )
                        if expiration > now:
                            cached_candidates.append(
                                (expiration, cached_credentials)
                            )
                    except Exception:
                        continue
                if cached_candidates:
                    credentials = max(
                        cached_candidates,
                        key=lambda item: item[0],
                    )[1]
            if credentials:
                env.update({
                    "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                    "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
                    "AWS_SESSION_TOKEN": credentials["SessionToken"],
                })
                # Force the Claude child to use the exported credentials.
                # Leaving AWS_PROFILE set makes its SDK prefer the expired
                # SSO bearer token over these valid role credentials.
                env.pop("AWS_PROFILE", None)
        except Exception as exc:
            log.warning(
                "[CLAUDE] Could not export cached AWS role credentials: %s",
                exc,
            )
    return env


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("response did not contain a JSON object")
    parsed = json.loads(candidate[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("parsed response is not a JSON object")
    return parsed


def _slot120_generate(prompt: str, *, timeout: int = 180, num_predict: int = 5000) -> str:
    """Invoke Qwen3.6 with its certified raw-safe ChatML framing."""
    framed_prompt = (
        "<|im_start|>system\n"
        "You are the AIMS deep reasoning and professional document generation model."
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"{prompt}"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
        "<think>\n\n</think>\n\n"
    )
    body = json.dumps({
        "model": ModelConfig.SLOT120_REASONING,
        "prompt": framed_prompt,
        "raw": True,
        "stream": True,
        "keep_alive": "6h",
        "options": {
            "temperature": 0.15,
            "num_ctx": SLOT120_NUM_CTX,
            "num_predict": num_predict,
            "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
        },
    }).encode()
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    done_reason = ""
    prompt_eval_count = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            chunks.append(str(event.get("response", "")))
            if event.get("done"):
                done_reason = str(event.get("done_reason", ""))
                prompt_eval_count = int(event.get("prompt_eval_count", 0) or 0)
    generated = "".join(chunks).strip()

    # Strip <think>...</think> reasoning blocks — must never appear in document output.
    # Two-pass: first closed blocks, then any unclosed <think> tail
    # (qwen35 may open a new <think> after the injected empty block, without closing it)
    import re as _re
    think_blocks = _re.findall(r"<think>.*?</think>", generated, flags=_re.DOTALL)
    if think_blocks:
        log.debug(f"[SLOT120] Stripping {len(think_blocks)} closed <think> block(s) from output")
        generated = _re.sub(r"<think>.*?</think>\s*", "", generated, flags=_re.DOTALL).strip()
    # Remove unclosed <think>...</end-of-string> tail
    if "<think>" in generated:
        before = len(generated)
        generated = _re.sub(r"<think>.*$", "", generated, flags=_re.DOTALL).strip()
        log.warning(f"[SLOT120] Stripped unclosed <think> tail ({before - len(generated)} chars)")

    if len(generated) < 200:
        raise RuntimeError(
            f"slot120 returned insufficient content: {len(generated)} chars; "
            f"done_reason={done_reason}"
        )
    log.info(
        "[SLOT120] Full request processed: input_chars=%d "
        "prompt_eval_count=%d num_ctx=%d",
        len(framed_prompt),
        prompt_eval_count,
        SLOT120_NUM_CTX,
    )
    return generated


# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GenerationMetrics:
    """Track quality metrics across generation cycles."""
    cycle: int
    timestamp: str
    model_used: str

    # Structural metrics
    sections_found: int
    sections_expected: int
    section_coverage: float  # 0-1.0

    # Content metrics
    standards_found: int
    standards_expected: int
    standards_accuracy: float  # 0-1.0

    # Reference metrics
    themes_covered: list[str] = field(default_factory=list)
    themes_missing: list[str] = field(default_factory=list)
    reference_match: float = 0.0  # 0-1.0

    # Quality metrics
    structure_score: float = 0.0  # From doc_quality_eval
    standards_score: float = 0.0
    coverage_score: float = 0.0
    overall_score: float = 0.0  # Weighted average

    # Feedback
    axi_recommendations: list[str] = field(default_factory=list)
    changes_applied: list[str] = field(default_factory=list)


@dataclass
class OmiResult:
    """Omi agent result: internal standards search + draft generation."""
    internal_standards: list[str]
    draft_text: str
    generation_time: float
    model_used: str = "qwen36-reasoning-35b-v1"  # SLOT120_REASONING (production winner)


@dataclass
class AxiResult:
    """Axi agent result: external standards search + validation."""
    external_standards: dict  # {"standards": [...], "content": {...}}
    recommendations: list[str]
    axi_feedback: str
    validation_time: float
    model_used: str = "opus"


@dataclass
class ClaudeAuditResult:
    """Claude Code CLI audit: validates both Omi and Axi work."""
    omi_quality: dict  # {"standards_accuracy": 0.9, "completeness": 0.75, ...}
    axi_quality: dict  # {"standards_accuracy": 0.95, "completeness": 0.92, ...}
    overall_assessment: str
    missing_standards: list[str]
    audit_time: float
    recommendations_from_audit: list[str] = field(default_factory=list)
    skill_recommendations: list[str] = field(default_factory=list)
    reference_gap: dict = field(default_factory=dict)
    bedrock_invoked: bool = False  # True if bedrock_doc_audit() returned successfully


@dataclass
class CycleResult:
    """Result of one generation cycle."""
    cycle_num: int
    success: bool
    generated_doc_path: Path
    metrics: GenerationMetrics
    axi_feedback: str
    ready_for_next_cycle: bool
    convergence_score: float  # 0-1.0, how close to reference
    omi_result: Optional[OmiResult] = None
    axi_result: Optional[AxiResult] = None
    audit_result: Optional[ClaudeAuditResult] = None
    bedrock_invoked: bool = False  # True if Bedrock audit was successfully invoked


def _evaluate_cycle_hard_gate(
    *,
    gate,
    struct_report,
    audit_schema_passed: bool,
    audit_quality_passed: bool,
    audit_quality_failures: list[str],
    rec_lineage_passed: bool,
    critical_regression: bool,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not gate.allowed:
        failures.append(gate.reason)
    if not struct_report.passed:
        failures.append(
            f"detailed_structure={struct_report.completeness_ratio:.1%} < "
            f"{struct_report.threshold:.0%}"
        )
    if not audit_schema_passed:
        failures.append("claude_audit_schema=FAIL")
    elif not audit_quality_passed:
        failures.extend(audit_quality_failures or ["claude_audit_quality=FAIL"])
    if not rec_lineage_passed:
        failures.append("recommendation_lineage=FAIL")
    if critical_regression:
        failures.append("critical_regression=true")
    return not failures, failures


def _evaluate_audit_quality(
    audit_result: Optional[ClaudeAuditResult],
    *,
    max_reference_gap: float = 0.25,
    min_agent_quality: float = 0.70,
) -> tuple[bool, list[str]]:
    """Require teacher acceptance, not merely parseable audit JSON."""
    if audit_result is None:
        return False, ["claude_audit_schema=FAIL"]

    failures: list[str] = []
    gap = float(audit_result.reference_gap.get("gap_score", 1.0))
    missing = audit_result.reference_gap.get("missing_sections", [])
    omi_avg = sum(audit_result.omi_quality.values()) / max(
        len(audit_result.omi_quality),
        1,
    )
    axi_avg = sum(audit_result.axi_quality.values()) / max(
        len(audit_result.axi_quality),
        1,
    )
    if gap > max_reference_gap:
        failures.append(
            f"claude_reference_gap={gap:.1%} > {max_reference_gap:.0%}"
        )
    if missing:
        failures.append(f"claude_missing_sections={len(missing)}")
    if omi_avg < min_agent_quality:
        failures.append(
            f"claude_omi_quality={omi_avg:.1%} < {min_agent_quality:.0%}"
        )
    if axi_avg < min_agent_quality:
        failures.append(
            f"claude_axi_quality={axi_avg:.1%} < {min_agent_quality:.0%}"
        )
    return not failures, failures


def _build_repair_plan(
    axi_recommendations: list[str],
    audit_recommendations: list[str],
    *,
    max_targets: int = 12,
    max_recommendations: int = 24,
    max_per_target: int = 2,
    use_phase1_convergence: bool = True,
    doc_text: str | None = None,
) -> dict[str, Any]:
    """Select a bounded, deterministic batch and preserve the full backlog.

    If use_phase1_convergence=True, applies DOCSREG Phase 1 staged convergence
    logic to prioritize STRUCTURE_CRITICAL and STRUCTURE_HIGH recommendations,
    deferring nesting/content/formatting changes to later phases.
    """
    # Combine recommendations for Phase 1 priority filtering (if enabled)
    all_recommendations = list(audit_recommendations) + list(axi_recommendations)
    phase1_metrics = None  # Will be populated if Phase 1 is enabled

    if use_phase1_convergence and all_recommendations:
        # Apply Phase 1 convergence: select only STRUCTURE_CRITICAL and STRUCTURE_HIGH (max 6 per phase)
        orchestrator = Phase1ConvergenceOrchestrator(
            max_recommendations_per_phase=4
        )
        phase1_batch = orchestrator.prepare_phase1_batch(all_recommendations)

        # Capture Phase 1 classification metrics for repair_plan output
        phase1_metrics = {
            "enabled": True,
            "selected_count": phase1_batch["phase1_count"],
            "deferred_count": phase1_batch["phase1_deferred_count"],
            "by_tier": phase1_batch["by_tier"],
            "total_classified": phase1_batch["classification_result"].total,
            "classifier_version": phase1_batch["classifier_version"],
        }

        # Use Phase 1 selected recommendations, log the distribution
        log.info(
            f"Phase 1 convergence: {phase1_batch['phase1_count']} selected "
            f"({phase1_batch['by_tier']}) from {phase1_batch['classification_result'].total} total; "
            f"{phase1_batch['phase1_deferred_count']} deferred to later phases"
        )

        candidates = [
            ("phase1_selected", item)
            for item in phase1_batch["phase1_selected"]
        ]

        # Phase 3: content quality — deferred recs + auto-detected stubs/fabricated standards
        phase3_metrics: dict[str, Any] = {"enabled": False}
        if doc_text:
            deferred_recs = phase1_batch["classification_result"].deferred
            phase3_result = select_phase3_recommendations(doc_text, deferred_recs)
            phase3_metrics = {
                "enabled": True,
                "selected_count": len(phase3_result["selected"]),
                "stub_sections": phase3_result["stub_sections"],
                "fabricated_standards_sections": phase3_result["fabricated_standards_sections"],
                "total_from_deferred": phase3_result["total_from_deferred"],
                "total_auto_generated": phase3_result["total_auto_generated"],
                "status": phase3_result["status"],
            }
            if phase3_result["selected"]:
                candidates += [
                    ("phase3_content_quality", item)
                    for item in phase3_result["selected"]
                ]
                log.info(
                    "Phase 3 content quality: %d selected (%d deferred + %d auto), status=%s",
                    len(phase3_result["selected"]),
                    phase3_result["total_from_deferred"],
                    phase3_result["total_auto_generated"],
                    phase3_result["status"],
                )
    else:
        phase1_metrics = {"enabled": False}
        phase3_metrics = {"enabled": False}
        candidates = [
            ("claude_audit", item)
            for item in audit_recommendations
        ] + [
            ("axi", item)
            for item in axi_recommendations
        ]

    selected: list[str] = []
    deferred: list[dict[str, str]] = []
    selected_targets: set[str] = set()
    per_target: dict[str, int] = {}
    seen: set[str] = set()

    for source, recommendation in candidates:
        dedupe_key = re.sub(r"\s+", " ", recommendation).strip().lower()
        if not dedupe_key or dedupe_key in seen:
            deferred.append({
                "source": source,
                "recommendation": recommendation,
                "reason": "duplicate_or_empty",
            })
            continue
        seen.add(dedupe_key)
        normalized = normalize_rec("PLAN", recommendation)
        target = normalized.target
        if target == "UNRESOLVED":
            deferred.append({
                "source": source,
                "recommendation": recommendation,
                "reason": "unresolved_target",
            })
            continue
        target_key = (
            f"NEW:{target}"
            if normalized.operation == "NEW_SECTION"
            else target
        )
        if target_key not in selected_targets and len(selected_targets) >= max_targets:
            deferred.append({
                "source": source,
                "recommendation": recommendation,
                "reason": "target_budget_exhausted",
            })
            continue
        target_limit = (
            1
            if normalized.operation == "NEW_SECTION"
            else max_per_target
        )
        if per_target.get(target_key, 0) >= target_limit:
            deferred.append({
                "source": source,
                "recommendation": recommendation,
                "reason": "per_target_budget_exhausted",
            })
            continue
        if len(selected) >= max_recommendations:
            deferred.append({
                "source": source,
                "recommendation": recommendation,
                "reason": "recommendation_budget_exhausted",
            })
            continue
        selected.append(recommendation)
        selected_targets.add(target_key)
        per_target[target_key] = per_target.get(target_key, 0) + 1

    return {
        "selected": selected,
        "deferred": deferred,
        "selected_count": len(selected),
        "deferred_count": len(deferred),
        "selected_targets": sorted(selected_targets),
        "limits": {
            "max_targets": max_targets,
            "max_recommendations": max_recommendations,
            "max_per_target": max_per_target,
        },
        "phase1_convergence": phase1_metrics,
        "phase3_content_quality": phase3_metrics,
    }


def _missing_section_recommendations(
    missing_sections: list[str],
) -> list[str]:
    """Convert teacher-reported numbered omissions into code-routable work."""
    recommendations: list[str] = []
    for missing in missing_sections:
        if re.match(r"^\s*Appendix\s+", missing, re.IGNORECASE):
            recommendations.append(missing)
            continue
        match = re.match(
            r"^\s*(?:(?:Sub-section|New Section|Section)\s+)?"
            r"(\d+(?:\.\d+)*)\s*:?\s+(.+?)\s*$",
            missing,
            re.IGNORECASE,
        )
        if not match:
            continue
        section_id, heading = match.groups()
        recommendations.append(
            f"Add new Section {section_id} {heading}"
        )
    return recommendations


def _runtime_preflight(output_dir: Path) -> dict[str, Any]:
    """Verify both routed models exist and projected Ollama VRAM stays below 95%."""
    output_dir.mkdir(parents=True, exist_ok=True)
    required_models = {
        "slot14": ModelConfig.SLOT14_SEARCH,
        "slot120": ModelConfig.SLOT120_REASONING,
    }
    listed = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    available = listed.stdout
    missing = [
        model for model in required_models.values()
        if model not in available and model.removesuffix(":latest") not in available
    ]

    loaded_vram = 0
    loaded_model_names: set[str] = set()
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5) as response:
            loaded = json.loads(response.read())
        loaded_models = loaded.get("models", [])
        loaded_vram = sum(
            int(item.get("size_vram", 0))
            for item in loaded_models
        )
        for item in loaded_models:
            for key in ("name", "model"):
                name = str(item.get(key, "")).strip()
                if name:
                    loaded_model_names.add(name)
                    loaded_model_names.add(name.removesuffix(":latest"))
    except Exception as exc:
        raise RuntimeError(f"Cannot read Ollama runtime state: {exc}") from exc

    required_bytes = 0
    for model in required_models.values():
        if (
            model in loaded_model_names
            or model.removesuffix(":latest") in loaded_model_names
        ):
            continue
        if model in available or model.removesuffix(":latest") in available:
            for line in available.splitlines()[1:]:
                if line.startswith(model.removesuffix(":latest")):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            size = float(parts[2])
                            unit = parts[3].upper() if len(parts) > 3 else "GB"
                            required_bytes += int(size * (1024**3 if unit == "GB" else 1024**2))
                        except (ValueError, IndexError):
                            pass
                    break

    total_vram = 128 * 1024**3
    projected_fraction = min((loaded_vram + required_bytes) / total_vram, 1.0)
    result = {
        "status": "PASS" if not missing and projected_fraction < 0.95 else "BLOCKED",
        "required_models": required_models,
        "missing_models": missing,
        "loaded_vram_gb": round(loaded_vram / 1024**3, 3),
        "projected_vram_fraction": round(projected_fraction, 5),
        "vram_limit_fraction": 0.95,
        "destructive_actions": False,
        "teacher_judge_provider": "claude_code_cli_aws",
        "slot120_teacher": False,
        "slot120_judge": False,
    }
    (output_dir / "runtime_preflight.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if result["status"] != "PASS":
        raise RuntimeError(f"Runtime preflight blocked: {result}")
    return result


def _slot14_route_topic(topic: str, output_dir: Path) -> str:
    """Use the slot14 operational model to normalize the Axi/Omi document request."""
    prompt = (
        "Classify this document-generation request for AIMS. Return one JSON object "
        "with action='search', query, doc_type, and language. Request: "
        f"{topic}"
    )
    body = json.dumps({
        "model": ModelConfig.SLOT14_SEARCH,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "4h",
    }).encode()
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            ollama_response = json.loads(response.read())
        raw_response = str(ollama_response.get("response", ""))
        route = {
            "model": ModelConfig.SLOT14_SEARCH,
            "status": "PASS",
            "response": raw_response,
        }
    except Exception as exc:
        route = {
            "model": ModelConfig.SLOT14_SEARCH,
            "status": "FAIL",
            "error": str(exc),
        }
        raw_response = ""
    (output_dir / "slot14_route.json").write_text(
        json.dumps(route, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if route["status"] != "PASS":
        raise RuntimeError(f"slot14 routing failed: {route.get('error', '')}")
    try:
        parsed = _extract_json_object(raw_response)
        return str(parsed.get("query") or topic)
    except (json.JSONDecodeError, ValueError):
        log.warning("[SLOT14] Non-JSON route response; preserving original topic")
        return topic


def _claude_judge_smoke(output_dir: Path) -> dict[str, Any]:
    """Require a real Bedrock-backed structured judgment before generation starts."""
    prompt = (
        "Evaluate two answers to the arithmetic question 'What is 2+2?'. "
        "Candidate A says '4'. Candidate B says '5'. Return JSON only with "
        "verdict='A', integer score from 1 to 10, and a short rationale."
    )
    smoke: dict[str, Any] = {
        "provider": "aws_bedrock_boto3",
        "status": "FAIL",
        "attempts": [],
    }
    forced_model = os.getenv("AIMS_CLAUDE_JUDGE_MODEL", "").strip().lower()
    if forced_model in {"opus", "sonnet"}:
        model_attempts = ((forced_model, 120),)
    else:
        model_attempts = (("opus", 90), ("sonnet", 120))

    # Map model names to Bedrock inference profile IDs
    model_id_map = {
        "sonnet": "us.anthropic.claude-sonnet-4-6",
        "opus": "us.anthropic.claude-opus-4-6-v1"
    }

    for attempt_number, (model, timeout_seconds) in enumerate(
        model_attempts,
        start=1,
    ):
        attempt: dict[str, Any] = {
            "attempt": attempt_number,
            "model": model,
            "timeout_seconds": timeout_seconds,
        }
        try:
            import boto3

            # Create Bedrock client with AdministratorAccess profile
            session = boto3.Session(
                profile_name="AdministratorAccess-445100240501",
                region_name="us-east-1"
            )
            bedrock = session.client("bedrock-runtime")

            # Call Bedrock invoke_model API (Messages API format)
            model_id = model_id_map[model]
            request_body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.0,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            })

            response = bedrock.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=request_body
            )

            # Parse response
            response_body = json.loads(response["body"].read())
            response_text = response_body["content"][0]["text"]
            stop_reason = response_body.get("stop_reason", "unknown")

            # Parse JSON from response
            judged = _extract_json_object(response_text)
            valid = (
                stop_reason == "end_turn"
                and judged.get("verdict") == "A"
                and isinstance(judged.get("score"), int)
                and judged["score"] > 0
            )
            attempt.update(
                {
                    "returncode": 0,
                    "stderr": "",
                    "raw_stdout": response_text,
                    "wrapper": {"result": response_text, "is_error": False},
                    "parsed": judged,
                    "status": "PASS" if valid else "FAIL",
                    "bedrock_stop_reason": stop_reason,
                    "bedrock_usage": response_body.get("usage", {})
                }
            )
            smoke["attempts"].append(attempt)
            if valid:
                smoke.update(
                    {
                        "status": "PASS",
                        "passed_attempt": attempt_number,
                        "model": model,
                        "degraded_mode": model != "opus",
                        "parsed": judged,
                    }
                )
                break
        except Exception as exc:
            # Catch boto3 exceptions (ClientError, TimeoutError, etc.)
            attempt.update(
                {
                    "status": "ERROR",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            smoke["attempts"].append(attempt)

    (output_dir / "claude_judge_smoke.json").write_text(
        json.dumps(smoke, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if smoke["status"] != "PASS":
        incident = {
            "classification": "DOCUMENT_CYCLE_BLOCKED_CLAUDE_JUDGE_SMOKE",
            "reason": "Claude Code AWS judge smoke did not return valid judgment JSON",
            "generation_started": False,
            "attempts": smoke["attempts"],
        }
        (output_dir / "DOCUMENT_CYCLE_BLOCKED.json").write_text(
            json.dumps(incident, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        raise RuntimeError(
            "Claude Code AWS judge smoke failed; document cycle blocked"
        )
    return smoke


# ──────────────────────────────────────────────────────────────────────────────
# SEARCH STANDARDS — Two-Level Injection
# ──────────────────────────────────────────────────────────────────────────────

def _search_internal_standards(topic: str, max_results: int = 20) -> list[str]:
    """
    Omi searches internal standards database (Qdrant RAG + SQLite).
    Fast, local, based on internal document registry.
    """
    log.info(f"[OMI-SEARCH] Querying internal standards database for: {topic}")

    try:
        from ops.docagent.doc_skills import DocSkillRunner

        runner = DocSkillRunner()
        results = runner.invoke("doc-search", query=topic, mode="hybrid", max_results=max_results)

        if results and isinstance(results, dict):
            standards = results.get("standards", [])
            if standards:
                log.info(f"[OMI-SEARCH] Found {len(standards)} internal standards via DocSkillRunner")
                return standards[:max_results]
    except Exception as e:
        log.warning(f"[OMI-SEARCH] DocSkillRunner failed: {e}")

    # Direct Qdrant vector search against intl_standards (34k indexed clauses)
    try:
        from ops.docagent.standards_rag import _embed, _search, _collection_exists

        if _collection_exists():
            vector = _embed(topic)
            clauses = _search(vector, top_k=max_results)
            if clauses:
                standards = [
                    f"{c.citation()}: {c.text[:400]}"
                    for c in clauses
                ]
                log.info(f"[OMI-SEARCH] Found {len(standards)} clauses via Qdrant direct search")
                return standards
            log.warning("[OMI-SEARCH] Qdrant search returned no clauses")
        else:
            log.warning("[OMI-SEARCH] intl_standards collection not available")
    except Exception as e:
        log.warning(f"[OMI-SEARCH] Qdrant direct search failed: {e}")

    # Final fallback: governed hardcoded set
    log.warning("[OMI-SEARCH] Using governed fallback standards set")
    return [
        "ISO 55001:2014 Asset Management",
        "ISO 55002:2018 Asset Management - Implementation guidance",
        "ISO 45001:2018 Occupational Health & Safety",
        "API 510 Pressure Vessel Inspection Code",
        "API 570 Piping Code",
        "API 580 Risk-Based Inspection",
        "ASME B31.3 Process Piping",
        "IEC 61511-1 Safety Instrumented Systems",
        "NACE SP0169 Cathodic Protection Standard",
    ]


# Keywords that indicate a standard is off-topic for asset integrity management.
# Qdrant vector search often returns electrical/instrumentation standards that
# look "similar" to AIMS documents but are never cited in the reference policy.
_ELECTRICAL_NOISE_PREFIXES = (
    "iec 60",  # IEC power/transformer series
    "iec 61",  # IEC safety/instrumentation series — most are off-topic for policy
    "ip 15",   # hazardous area classification (electrical)
    "bs en",   # British electrical standards that leak into AIMS queries
    "ansi/nema",
    "ieee",
)

_AIMS_RELEVANT_KEYWORDS = (
    "asset", "integrity", "iso 55", "api 5", "api 58", "asme", "maintenance",
    "inspection", "risk", "pressure", "vessel", "piping", "corrosion", "reliability",
    "ims", "hseq", "occupational", "safety management",
)


def _filter_standards_for_reference(
    qdrant_standards: list[str],
    reference_text: str,
) -> list[str]:
    """
    When a reference document is available, prefer standards cited in it over
    noisy Qdrant results. Falls back to keyword filtering if reference extraction
    fails.

    Strategy:
    1. Extract standard identifiers from the reference text's "References" section.
    2. Return those directly if ≥ 2 were found (reference-grounded).
    3. Otherwise filter Qdrant results, removing obvious electrical/off-topic
       entries whose identifier prefix matches _ELECTRICAL_NOISE_PREFIXES.
    """
    # --- Step 1: extract standards from reference "References" or "6.0" section ---
    extracted: list[str] = []
    if reference_text:
        lines = reference_text.splitlines()
        in_refs = False
        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()
            # Enter references section
            if not in_refs and re.search(
                r"^(6\.0\s+REFERENCES?|REFERENCES?\s*$)", upper
            ):
                in_refs = True
                continue
            # Exit when next major section starts (e.g. "7.0 ...")
            if in_refs and re.match(r"^\d+\.0\s+", stripped) and not re.match(
                r"^6\.", stripped
            ):
                break
            if in_refs and stripped:
                # Accept lines that look like a standard citation
                if re.search(r"\b(ISO|API|ASME|IEC|NACE|ANSI|IEEE)\b", stripped, re.I):
                    extracted.append(stripped)

    if len(extracted) >= 2:
        log.info(
            "[STANDARDS-FILTER] Using %d reference-extracted standards instead of Qdrant",
            len(extracted),
        )
        return extracted[:20]

    # --- Step 2: filter Qdrant results by keyword relevance ---
    filtered: list[str] = []
    rejected: list[str] = []
    for s in qdrant_standards:
        s_lower = s.lower()
        if any(s_lower.lstrip("- ").startswith(p) for p in _ELECTRICAL_NOISE_PREFIXES):
            rejected.append(s[:60])
            continue
        if any(kw in s_lower for kw in _AIMS_RELEVANT_KEYWORDS):
            filtered.append(s)
        else:
            rejected.append(s[:60])

    if rejected:
        log.info(
            "[STANDARDS-FILTER] Removed %d off-topic standards from Qdrant results: %s",
            len(rejected),
            rejected[:5],
        )

    # If filtering removed everything, keep the AIMS-management-relevant subset of fallback
    if not filtered:
        return [
            "ISO 55001:2014 Asset Management Systems — Requirements",
            "ISO 55002:2018 Asset Management — Guidelines",
            "ISO 45001:2018 Occupational Health & Safety Management Systems",
        ]
    return filtered


def _search_external_standards(topic: str, doc_text: str) -> dict:
    """
    Axi searches INTERNET via skill_search() to find external standards.

    Returns:
    {
        "standards": ["ISO 55002", "API 570", ...],
        "content": {
            "ISO 55002": "extracted content/requirements",
            ...
        }
    }
    """
    log.info(f"[AXI-INTERNET-SEARCH] Searching for external standards on: {topic}")

    try:
        # Try to import and use DocSkillRunner for doc-search with internet mode
        from ops.docagent.doc_skills import DocSkillRunner

        runner = DocSkillRunner()

        # Call doc-search with internet mode to find external standards
        search_results = runner.invoke(
            "doc-search",
            query=f"standards guidelines requirements for {topic}",
            mode="internet",  # External search mode
            max_results=5
        )

        if search_results and isinstance(search_results, dict):
            external_standards = search_results.get("standards", [])
            content_map = search_results.get("content", {})

            log.info(f"[AXI-INTERNET-SEARCH] Found {len(external_standards)} external standards")
            log.info(f"[AXI-INTERNET-SEARCH] Standards: {external_standards}")

            return {
                "standards": external_standards,
                "content": content_map
            }
    except Exception as e:
        log.warning(f"[AXI-INTERNET-SEARCH] skill_search failed: {e}")

    return {"standards": [], "content": {}}


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 1: OMI — Draft Generation with Standards Context
# ──────────────────────────────────────────────────────────────────────────────

def _omi_generate_draft(
    topic: str,
    context: Optional[str] = None,
    reference_template: Optional[str] = None,
    standards_to_inject: Optional[list[str]] = None,
    search_internal: bool = True,
    grounded_prompt: Optional[str] = None,
) -> str:
    """
    Omi generates initial document draft.

    1. Searches internal standards database (Qdrant RAG + SQLite)
    2. Injects standards context before generation
    3. Foundation: establish proper ADNOC structure, roles, scope, references
    """
    log.info(f"[OMI] Generating draft for topic: {topic}")

    # If no standards provided, search internal database
    if not standards_to_inject and search_internal:
        standards_to_inject = _search_internal_standards(topic, max_results=20)
        log.info(f"[OMI] Auto-injected {len(standards_to_inject)} standards from internal database")

    if grounded_prompt:
        prompt = grounded_prompt
    else:
        # Build prompt with injected standards and reference structure hints
        prompt_parts = [
            f"Generate a comprehensive professional document on:\n{topic}\n\n",
            "STRUCTURAL REQUIREMENTS:",
            "- Document Control & Distribution (with revision history)",
            "- Table of Contents (numbered sections)",
            "- Introduction & Purpose/Objective",
            "- Scope (applicability, lifecycle coverage)",
            "- Policy/Framework elements (list all)",
            "- Definitions & Acronyms",
            "- References (standards, guidelines, industry best practices)",
            "- Framework Overview (PDCA cycle, lifecycle aspects)",
            "- Elements & Sub-elements with expectations",
            "- Operational integrity guidance",
            "- Appendices\n\n",
        ]

        if standards_to_inject:
            prompt_parts.append(
                "MANDATORY STANDARDS TO INCLUDE:\n"
                f"{chr(10).join(standards_to_inject)}\n\n"
            )

        if reference_template:
            prompt_parts.append(
                "REFERENCE TEMPLATE STRUCTURE AND CONTENT:\n"
                f"{reference_template}\n\n"
            )

        prompt_parts.append(
            "Style: Official corporate document (ADNOC/Oil & Gas standards compliance)\n"
            "Language: English, professional terminology\n"
            "Format: Markdown with proper headings, emphasis on clarity and compliance\n"
            "Length: 2500-3500 words for this controlled improvement cycle\n"
        )
        prompt = "".join(prompt_parts)

    # Call Omi reasoning model through the certified Qwen3.6 raw-safe protocol.
    try:
        generated = _slot120_generate(prompt, timeout=180, num_predict=5000)
        log.info(
            "[OMI] Draft generation complete (%d chars, model=%s)",
            len(generated),
            ModelConfig.SLOT120_REASONING,
        )
        return generated
    except TimeoutError:
        log.error("[OMI] Generation timeout")
        return ""
    except Exception as e:
        log.error(f"[OMI] Generation error: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 2: QUALITY EVALUATION — Structure, Standards, Coverage
# ──────────────────────────────────────────────────────────────────────────────

def _evaluate_document_quality(
    doc_text: str,
    topic: str,
    reference_text: Optional[str] = None,
) -> GenerationMetrics:
    """
    Evaluate generated document against:
    1. ADNOC structural requirements
    2. Standards accuracy & completeness
    3. Reference template coverage
    """
    log.info("[EVAL] Starting quality evaluation...")

    # Try to use doc_quality_eval module
    try:
        from ops.docagent.doc_quality_eval import evaluate_document
        result = evaluate_document(
            doc_text,
            topic=topic,
            reference_text=reference_text,
        )

        # Convert to our metrics
        metrics = GenerationMetrics(
            cycle=0,  # Will be updated by caller
            timestamp=datetime.now().isoformat(),
            model_used=ModelConfig.SLOT120_REASONING,
            sections_found=len(result.structure_details),
            sections_expected=15,  # ADNOC baseline
            section_coverage=result.structure_score,
            standards_found=len(result.standards_details.get("found_standards", [])),
            standards_expected=10,  # Baseline for Asset Integrity
            standards_accuracy=result.standards_score,
            themes_covered=result.reference_comparison.reference_sections if hasattr(result, 'reference_comparison') else [],
            reference_match=result.reference_score,
            structure_score=result.structure_score,
            standards_score=result.standards_score,
            coverage_score=result.reference_score,
            overall_score=(result.structure_score + result.standards_score + result.reference_score) / 3,
        )
        log.info(f"[EVAL] Quality scores: structure={metrics.structure_score:.2f}, standards={metrics.standards_score:.2f}, coverage={metrics.reference_match:.2f}")
        return metrics
    except Exception as e:
        log.warning(f"[EVAL] doc_quality_eval unavailable: {e}, using basic eval")

    # Fallback: basic evaluation
    metrics = GenerationMetrics(
        cycle=0,
        timestamp=datetime.now().isoformat(),
        model_used=ModelConfig.SLOT120_REASONING,
        sections_found=doc_text.count("#"),  # Count headings
        sections_expected=15,
        section_coverage=min(doc_text.count("#") / 15.0, 1.0),
        standards_found=sum(1 for std in ["ISO", "API", "ASME", "NACE", "IEC"] if std in doc_text),
        standards_expected=10,
        standards_accuracy=0.0,  # Would need NLP
        reference_match=0.0,
        structure_score=min(doc_text.count("#") / 15.0, 1.0),
        standards_score=0.0,
        coverage_score=0.0,
        overall_score=min(doc_text.count("#") / 15.0, 1.0),
    )
    return metrics


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 3: AXI VALIDATION — High-Rank Claude Recommendations
# ──────────────────────────────────────────────────────────────────────────────

def _axi_validate_and_recommend(
    doc_text: str,
    metrics: GenerationMetrics,
    topic: str,
    reference_text: Optional[str] = None,
    search_external: bool = True,
) -> tuple[str, list[str]]:
    """
    Axi calls high-rank Claude model (via gateway) to:
    1. Validate document structure and content
    2. Find gaps vs. reference template
    3. Recommend specific improvements
    4. Search external sources for missing standards
    5. Identify gaps not covered by internal database
    """
    log.info(f"[AXI] Validating generation quality (cycle metrics: overall={metrics.overall_score:.2f})...")

    # Search external standards if enabled
    external_standards_data = {"standards": [], "content": {}}
    if search_external:
        external_standards_data = _search_external_standards(topic, doc_text)

    # Build validation prompt with external standards context
    external_context = ""
    if external_standards_data["standards"]:
        standards_list = "\n".join(external_standards_data["standards"])
        external_context = f"\n\nEXTERNAL STANDARDS FOUND (from internet search):\n{standards_list}\n"

        for std, content in external_standards_data["content"].items():
            external_context += f"\n{std} REQUIREMENTS:\n{content[:500]}...\n"

    # Prepare validation prompt with external standards
    validation_prompt = f"""You are an expert document validator for Oil & Gas Asset Integrity Management.

GENERATED DOCUMENT (Omi draft — full text):
{doc_text}

REFERENCE DOCUMENT — FULL AVAILABLE TEXT:
{reference_text or "(no reference text available)"}

CURRENT METRICS:
- Structure coverage: {metrics.section_coverage:.1%}
- Standards accuracy: {metrics.standards_accuracy:.1%}
- Reference match: {metrics.reference_match:.1%}
- Overall quality: {metrics.overall_score:.1%}
{external_context}

REFERENCE REQUIREMENTS:
- Document type: {topic}
- Expected framework: all 23 AIMS elements plus governed supporting sections
- Expected standards: ISO 55001, ISO 55002, ISO 45001, API standards, ASME standards
- Expected elements: PDCA framework, lifecycle management, operational integrity

VALIDATION & IMPROVEMENT TASKS:
1. List major structural gaps (missing sections, improper ordering)
2. Identify missing or incorrectly cited standards
3. **Analyze external standards found** - what requirements should be added to the document?
4. Propose SPECIFIC improvements to integrate the external standards
   - For each external standard found: "Section X: Add Y from [standard]"
5. Rate convergence to reference (0-100%)
6. Return at most 15 recommendations, at most 2 per exact section target
7. Use recommendations=[] when there is no material, verifiable gap

RESPOND WITH STRICT JSON ONLY:
{{
  "validation_passed": true/false,
  "structural_gaps": ["gap1", "gap2", ...],
  "external_standards_to_integrate": ["ISO 55002: Add implementation guidance section", ...],
  "improvement_recommendations": ["Section X: specific change", ...],
  "convergence_score": 0.XX,
  "summary": "one paragraph assessment"
}}"""

    try:
        # Axi recommendation pass uses Sonnet via direct Bedrock API.
        # Opus is reserved for the independent teacher/judge audit below.
        result_text = bedrock_axi_validate(validation_prompt, timeout=420)

        if result_text:
            try:
                validation_data = parse_json_from_response(result_text)
                feedback = validation_data.get("summary", "")
                recommendations = validation_data.get("improvement_recommendations", [])
                convergence_raw = float(validation_data.get("convergence_score", 0.0))
                convergence = (
                    convergence_raw / 100.0
                    if convergence_raw > 1.0
                    else convergence_raw
                )
                log.info(f"[AXI] Validation complete: convergence={convergence:.1%}, {len(recommendations)} recommendations")
                return feedback, recommendations
            except (ValueError, json.JSONDecodeError):
                log.warning("[AXI] Could not parse Bedrock validation response")
    except Exception as exc:
        log.error("[AXI] Validation call failed: %s", exc)

    # Fallback: basic recommendations
    recommendations = [
        "Add formal Document Control section with revision history",
        "Include complete Table of Contents with page numbers",
        "Expand Definitions & Acronyms section",
        "Add cross-references to applicable standards",
        "Ensure PDCA framework is clearly outlined",
        "Add Element-by-element expectations with sub-elements",
    ]
    feedback = "Fallback evaluation - standard recommendations applied"
    return feedback, recommendations


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 3B: CLAUDE CODE AUDIT — Independent Validation of Omi & Axi
# ──────────────────────────────────────────────────────────────────────────────

def _split_into_sections(text: str) -> dict[str, str]:
    """Split document into {heading: body} chunks by Markdown headings."""
    sections: dict[str, str] = {}
    current_heading = "__preamble__"
    current_body: list[str] = []

    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            if current_body:
                sections[current_heading] = "\n".join(current_body).strip()
            current_heading = m.group(2).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        sections[current_heading] = "\n".join(current_body).strip()

    return sections


def _run_claude_prompt(prompt: str, timeout: int = 300) -> Optional[str]:
    """Execute a single Claude Code CLI call, return result text or None."""
    result = subprocess.run(
        ["claude", "--print", "--output-format", "json", "--model", "opus", "--setting-sources="],
        input=prompt,
        env=_claude_bedrock_env(),
        capture_output=True,
        timeout=timeout,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.warning(f"[CLAUDE] CLI returned {result.returncode}: {result.stderr[:200]}")
        return None
    try:
        wrapper = json.loads(result.stdout)
        return wrapper.get("result", "")
    except (json.JSONDecodeError, KeyError):
        return None


def _audit_section_batch(
    batch_idx: int,
    section_batch: list[str],
    doc_sections: dict[str, str],
    omi_standards_str: str,
    axi_standards_str: str,
    axi_recs_str: str,
    topic: str,
    reference_text: str,
    cycle: int,
    model: str,
    evidence_dir: Optional[Path],
) -> list[dict]:
    """Run one Bedrock call auditing a section batch; return validated section_findings."""
    batch_text = "\n\n".join(
        f"### {name}\n{doc_sections[name]}" for name in section_batch if name in doc_sections
    )
    # Build per-section reference excerpts so the auditor sees relevant reference
    # content for each section rather than the same truncated front-matter prefix.
    ref_parts: list[str] = []
    for name in section_batch:
        # Section names are like "8.4 Element 4: Leadership…" — extract numeric ID.
        m = re.match(r"^\s*(\d+(?:\.\d+)*)", name)
        sid = m.group(1) if m else ""
        excerpt = _extract_reference_section(reference_text, sid) if (reference_text and sid) else ""
        if excerpt:
            ref_parts.append(f"[{name}]\n{excerpt}")
    ref_block = (
        "\n\n".join(ref_parts)
        if ref_parts
        else (reference_text[:6000] if reference_text else "(none)")
    )
    batch_prompt = (
        f"You are an independent auditor for an Asset Integrity Management document.\n\n"
        f"TOPIC: {topic}\n"
        f"CYCLE: {cycle}\n"
        f"BATCH: {batch_idx + 1}\n"
        f"SECTIONS IN THIS BATCH ({len(section_batch)}):\n"
        f"{json.dumps(section_batch, ensure_ascii=False)}\n\n"
        f"SECTION TEXTS:\n{batch_text}\n\n"
        f"REFERENCE CONTENT (per-section excerpts from source document):\n"
        f"{ref_block}\n\n"
        f"OMI STANDARDS FOUND:\n{omi_standards_str}\n\n"
        f"AXI STANDARDS FOUND:\n{axi_standards_str}\n\n"
        f"AXI RECOMMENDATIONS:\n{axi_recs_str}\n\n"
        f"gap_score means: 0.0 = section content matches reference well; "
        f"1.0 = section is completely missing/divergent from reference.\n\n"
        f"Audit ONLY the {len(section_batch)} sections listed above. "
        f"Return strict JSON with ONLY this key:\n"
        f'{{"section_findings":['
        f'{{"section":"...","gap_score":0.0,"recommendations":[],"missing_standards":[]}}'
        f']}}\n'
        f"Each listed section must appear exactly once. At most 2 recommendations per section."
    )
    batch_evidence = (evidence_dir / f"audit_batch_{batch_idx:02d}") if evidence_dir else None
    parsed = bedrock_doc_audit(
        prompt=batch_prompt,
        model_alias=model,
        max_tokens=8000,
        timeout=600,
        evidence_dir=batch_evidence,
    ) or {}

    findings = parsed.get("section_findings", [])
    if not isinstance(findings, list):
        log.warning("[CLAUDE-AUDIT] Batch %d: invalid section_findings type", batch_idx)
        return []

    valid: list[dict] = []
    for f in findings:
        if not isinstance(f, dict) or f.get("section") not in section_batch:
            continue
        gap = f.get("gap_score")
        if not isinstance(gap, (int, float)):
            continue
        # Canonicalize to exactly the 4 required keys so the shared validation
        # block in _claude_code_audit() does not reject unexpected extra keys.
        recs = f.get("recommendations", [])
        stds = f.get("missing_standards", [])
        valid.append({
            "section": f["section"],
            "gap_score": max(0.0, min(1.0, float(gap))),
            "recommendations": recs if isinstance(recs, list) else [],
            "missing_standards": stds if isinstance(stds, list) else [],
        })

    log.info("[CLAUDE-AUDIT] Batch %d: %d/%d sections valid", batch_idx, len(valid), len(section_batch))
    return valid


def _claude_code_audit(
    omi_standards: list[str],
    axi_standards: list[str],
    doc_excerpt: str,
    axi_recommendations: list[str],
    topic: str,
    reference_text: str = "",
    cycle: int = 0,
    structure_report: dict = None,
    evidence_dir: Optional[Path] = None,
    model: str = "opus",
) -> Optional[ClaudeAuditResult]:
    """Run one bounded full-document Claude audit with section-level output."""
    log.info(f"[CLAUDE-AUDIT] Starting independent validation (cycle={cycle})...")

    omi_standards_str = "\n".join(omi_standards) if omi_standards else "(none found)"
    axi_standards_str = "\n".join(axi_standards) if axi_standards else "(none found)"
    axi_recs_str = "\n".join(axi_recommendations) if axi_recommendations else "(none)"
    struct_info = json.dumps(structure_report, indent=2) if structure_report else "(not available)"
    start_time = datetime.now()
    bedrock_invoked = False  # Track whether bedrock_doc_audit() was successfully invoked

    doc_sections = {
        name: body
        for name, body in _split_into_sections(doc_excerpt).items()
        if name != "__preamble__" and body.strip()
    }
    section_names = list(doc_sections)

    # ── Chunked audit path (large documents) ───────────────────────────────
    # When section count exceeds _AUDIT_CHUNK_SIZE (14), split into batches
    # of ≤14 sections, call _audit_section_batch() per batch, then run a
    # lightweight synthesis call for document-level quality metrics.
    if len(section_names) > _AUDIT_CHUNK_SIZE:
        n_batches = -(-len(section_names) // _AUDIT_CHUNK_SIZE)  # ceil division
        log.info(
            "[CLAUDE-AUDIT] Chunked audit: %d sections → %d batches of ≤%d",
            len(section_names), n_batches, _AUDIT_CHUNK_SIZE,
        )
        all_findings: list[dict] = []
        for i in range(n_batches):
            batch = section_names[i * _AUDIT_CHUNK_SIZE : (i + 1) * _AUDIT_CHUNK_SIZE]
            all_findings.extend(
                _audit_section_batch(
                    batch_idx=i,
                    section_batch=batch,
                    doc_sections=doc_sections,
                    omi_standards_str=omi_standards_str,
                    axi_standards_str=axi_standards_str,
                    axi_recs_str=axi_recs_str,
                    topic=topic,
                    reference_text=reference_text,
                    cycle=cycle,
                    model=model,
                    evidence_dir=evidence_dir,
                )
            )

        # Coverage check (same threshold as single-pass path)
        audited_names = {f["section"] for f in all_findings}
        required_coverage = max(1, int(len(section_names) * 0.8))
        if len(audited_names) < required_coverage:
            log.warning(
                "[CLAUDE-AUDIT] Chunked coverage failure: audited=%d required=%d total=%d",
                len(audited_names), required_coverage, len(section_names),
            )
            return None

        # Synthesis call: derive document-level metrics from batch findings.
        # Only section summaries sent — no full text → cheap call.
        findings_summary = json.dumps(
            [{"section": f["section"], "gap_score": f["gap_score"]} for f in all_findings],
            ensure_ascii=False, indent=2,
        )
        synthesis_prompt = (
            f"You are the independent teacher/judge for an Asset Integrity Management document.\n\n"
            f"TOPIC: {topic}\n"
            f"CYCLE: {cycle}\n\n"
            f"SECTION AUDIT SUMMARY ({len(all_findings)} sections audited):\n"
            f"{findings_summary}\n\n"
            f"OMI STANDARDS FOUND:\n{omi_standards_str}\n\n"
            f"AXI STANDARDS FOUND:\n{axi_standards_str}\n\n"
            f"STRUCTURE REPORT:\n{struct_info}\n\n"
            f"Based on the section-level audit above, provide document-level quality metrics. "
            f"Return strict JSON with EXACTLY these keys and no others:\n"
            f'{{"omi_quality":{{"standards_accuracy":0.0,"completeness":0.0,"context_relevance":0.0}},'
            f'"axi_quality":{{"standards_accuracy":0.0,"completeness":0.0,"context_relevance":0.0}},'
            f'"overall_assessment":"...","missing_sections":[],"skill_recommendations":[]}}'
        )
        synthesis_evidence = (evidence_dir / "audit_synthesis") if evidence_dir else None
        synth_parsed: dict[str, Any] = bedrock_doc_audit(
            prompt=synthesis_prompt,
            model_alias=model,
            max_tokens=4000,
            timeout=300,
            evidence_dir=synthesis_evidence,
        ) or {}
        bedrock_invoked = bool(synth_parsed)  # True if bedrock_doc_audit() returned non-empty dict
        parse_error = "" if synth_parsed else "synthesis call returned None (using defaults)"

        # Reconstruct a complete parsed dict for the shared validation path below
        parsed: dict[str, Any] = {
            "section_findings": all_findings,
            "missing_sections": synth_parsed.get("missing_sections", []),
            "omi_quality": synth_parsed.get("omi_quality", {"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0}),
            "axi_quality": synth_parsed.get("axi_quality", {"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0}),
            "overall_assessment": synth_parsed.get("overall_assessment", "Chunked audit complete."),
            "skill_recommendations": synth_parsed.get("skill_recommendations", []),
        }
        log.info("[CLAUDE-AUDIT] Chunked audit: %d findings merged, synthesis %s",
                 len(all_findings), "OK" if synth_parsed else "DEFAULT")

    # ── Single-pass audit path (small/medium documents ≤ _AUDIT_CHUNK_SIZE) ─
    else:
        log.info(
            "[CLAUDE-AUDIT] Single-pass full audit: %d sections, "
            "%d document chars, %d reference chars",
            len(section_names), len(doc_excerpt), len(reference_text),
        )
        audit_prompt = f"""You are the independent teacher/judge for an Asset Integrity Management document.

TOPIC: {topic}
CYCLE: {cycle}
TEACHER/JUDGE MODEL: Claude Code CLI AWS {model}
GENERATED SECTION NAMES ({len(section_names)}):
{json.dumps(section_names, ensure_ascii=False)}

GENERATED DOCUMENT — FULL TEXT:
{doc_excerpt}

REFERENCE DOCUMENT — FULL AVAILABLE TEXT:
{reference_text or "(no reference text available)"}

OMI STANDARDS FOUND:
{omi_standards_str}

AXI STANDARDS FOUND:
{axi_standards_str}

AXI RECOMMENDATIONS:
{axi_recs_str}

STRUCTURE REPORT:
{struct_info}

Audit every generated section. Return strict JSON only with exactly these
top-level keys: section_findings, missing_sections, omi_quality, axi_quality,
overall_assessment, skill_recommendations.

Each section_findings item must contain exactly: section, gap_score,
recommendations, missing_standards. Each recommendation must name an exact
target, for example "Section 8.3: Add criticality matrix requirements".
Use recommendations=[] for sections without a material gap. Return at most
18 recommendations total and at most 2 recommendations for any one section.
Prioritize missing sections, safety-critical omissions, and reference gaps.

JSON SHAPE:
{{"section_findings":[{{"section":"...","gap_score":0.0,"recommendations":[],"missing_standards":[]}}],"missing_sections":[],"omi_quality":{{"standards_accuracy":0.0,"completeness":0.0,"context_relevance":0.0}},"axi_quality":{{"standards_accuracy":0.0,"completeness":0.0,"context_relevance":0.0}},"overall_assessment":"...","skill_recommendations":[]}}"""

        # max_tokens raised to 16000 (was 8000) — 14 sections × ~400 tokens/finding
        # = 5600 output, well within new limit; covers up to ~40 sections safely.
        parsed: dict[str, Any] = bedrock_doc_audit(
            prompt=audit_prompt,
            model_alias=model,
            max_tokens=16000,
            timeout=600,
            evidence_dir=evidence_dir,
        ) or {}
        bedrock_invoked = bool(parsed)  # True if bedrock_doc_audit() returned non-empty dict
        parse_error = "" if parsed else "bedrock_doc_audit returned None"  # Assign immediately after bedrock_invoked to preserve flag before validation early returns

    required = {
        "section_findings",
        "missing_sections",
        "omi_quality",
        "axi_quality",
        "overall_assessment",
        "skill_recommendations",
    }
    if parse_error or set(parsed) != required:
        log.warning("[CLAUDE-AUDIT] Invalid top-level schema; parse_error=%s bedrock_invoked=%s", parse_error, bedrock_invoked)
        # If bedrock was invoked but schema is invalid, still create a degraded result to preserve bedrock_invoked flag
        if bedrock_invoked:
            elapsed = (datetime.now() - start_time).total_seconds()
            return ClaudeAuditResult(
                omi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                axi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                overall_assessment=f"Bedrock audit returned invalid schema; parse_error={parse_error}",
                missing_standards=[],
                audit_time=elapsed,
                recommendations_from_audit=[],
                skill_recommendations=[],
                reference_gap={},
                bedrock_invoked=True,  # Preserve that bedrock was invoked
            )
        return None

    section_findings = parsed["section_findings"]
    if not isinstance(section_findings, list):
        log.warning("[CLAUDE-AUDIT] Invalid section_findings type (not list); bedrock_invoked=%s", bedrock_invoked)
        if bedrock_invoked:
            elapsed = (datetime.now() - start_time).total_seconds()
            return ClaudeAuditResult(
                omi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                axi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                overall_assessment="Bedrock audit returned invalid section_findings structure",
                missing_standards=[],
                audit_time=elapsed,
                recommendations_from_audit=[],
                skill_recommendations=[],
                reference_gap={},
                bedrock_invoked=True,
            )
        return None

    valid_findings: list[dict] = []
    audited_names: set[str] = set()
    all_recommendations: list[str] = []
    all_missing_standards: set[str] = set()
    for finding in section_findings:
        if not isinstance(finding, dict) or set(finding) != {
            "section",
            "gap_score",
            "recommendations",
            "missing_standards",
        }:
            return None
        if finding["section"] not in section_names:
            continue
        if not isinstance(finding["gap_score"], (int, float)):
            return None
        score = float(finding["gap_score"])
        if not 0.0 <= score <= 1.0:
            return None
        if not isinstance(finding["recommendations"], list):
            return None
        if not isinstance(finding["missing_standards"], list):
            return None
        if not all(isinstance(item, str) for item in finding["recommendations"]):
            return None
        if not all(isinstance(item, str) for item in finding["missing_standards"]):
            return None
        valid_findings.append(finding)
        audited_names.add(finding["section"])
        all_missing_standards.update(finding["missing_standards"])

    required_coverage = max(1, int(len(section_names) * 0.8))
    if len(audited_names) < required_coverage:
        log.warning(
            "[CLAUDE-AUDIT] Coverage failure: audited=%d required=%d total=%d; bedrock_invoked=%s",
            len(audited_names),
            required_coverage,
            len(section_names),
            bedrock_invoked,
        )
        # If bedrock was invoked but coverage is insufficient, still create a degraded result
        if bedrock_invoked:
            elapsed = (datetime.now() - start_time).total_seconds()
            return ClaudeAuditResult(
                omi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                axi_quality={"standards_accuracy": 0.0, "completeness": 0.0, "context_relevance": 0.0},
                overall_assessment=f"Bedrock audit coverage insufficient: {len(audited_names)}/{required_coverage} sections",
                missing_standards=list(all_missing_standards),
                audit_time=elapsed,
                recommendations_from_audit=all_recommendations,
                skill_recommendations=[],
                reference_gap={},
                bedrock_invoked=True,
            )
        return None

    missing_sections = parsed["missing_sections"]
    if not isinstance(missing_sections, list) or not all(
        isinstance(item, str) for item in missing_sections
    ):
        return None
    avg_gap = sum(float(f["gap_score"]) for f in valid_findings) / len(valid_findings)
    high_gap_sections = [
        f["section"] for f in valid_findings if float(f["gap_score"]) >= 0.4
    ]
    # Prefix each recommendation with its section ID so normalize_rec() can
    # resolve the target section without guessing from free-form text.
    all_recommendations = [
        f"Section {finding['section']}: {recommendation}"
        for finding in sorted(
            valid_findings,
            key=lambda item: float(item["gap_score"]),
            reverse=True,
        )
        for recommendation in finding["recommendations"]
    ]

    elapsed = (datetime.now() - start_time).total_seconds()

    omi_q = parsed["omi_quality"]
    axi_q = parsed["axi_quality"]
    skill_recs = parsed["skill_recommendations"]
    quality_keys = {
        "standards_accuracy",
        "completeness",
        "context_relevance",
    }
    if (
        not isinstance(omi_q, dict)
        or not isinstance(axi_q, dict)
        or set(omi_q) != quality_keys
        or set(axi_q) != quality_keys
        or not all(isinstance(value, (int, float)) for value in omi_q.values())
        or not all(isinstance(value, (int, float)) for value in axi_q.values())
        or not all(0.0 <= float(value) <= 1.0 for value in omi_q.values())
        or not all(0.0 <= float(value) <= 1.0 for value in axi_q.values())
    ):
        return None
    if not isinstance(skill_recs, list) or not all(
        isinstance(item, str) for item in skill_recs
    ):
        return None
    if not isinstance(parsed["overall_assessment"], str):
        return None
    ref_gap = {
        "gap_score": avg_gap,
        "missing_sections": missing_sections,
        "high_gap_sections": high_gap_sections,
        "sections_audited": len(valid_findings),
        "sections_expected": len(section_names),
        "audit_mode": "single_pass_full_document",
    }

    omi_avg = sum(omi_q.values()) / len(omi_q) if omi_q else 0
    axi_avg = sum(axi_q.values()) / len(axi_q) if axi_q else 0
    log.info(
        f"[CLAUDE-AUDIT] Complete in {elapsed:.0f}s — "
        f"sections={len(valid_findings)}, avg_gap={avg_gap:.1%}, "
        f"Omi:{omi_avg:.1%} Axi:{axi_avg:.1%}, "
        f"recs={len(all_recommendations)}, skill_recs={len(skill_recs)}"
    )

    return ClaudeAuditResult(
        omi_quality=omi_q,
        axi_quality=axi_q,
        overall_assessment=parsed["overall_assessment"],
        missing_standards=list(all_missing_standards),
        audit_time=elapsed,
        recommendations_from_audit=all_recommendations,
        skill_recommendations=skill_recs,
        reference_gap=ref_gap,
        bedrock_invoked=bedrock_invoked,
    )


# ──────────────────────────────────────────────────────────────────────────────
# STAGE 4: IMPROVEMENT CYCLE — Apply Recommendations
# ──────────────────────────────────────────────────────────────────────────────

def _apply_improvements(
    doc_text: str,
    recommendations: list[str],
    topic: str,
    external_standards: dict = None,
    audit_recommendations: list[str] = None,
) -> str:
    """
    Apply Axi + Claude audit recommendations + external standards to improve document.

    Flow:
    1. Merge Axi + Claude audit recommendations (teacher signal)
    2. Build improvement prompt with full document context
    3. Call SLOT120_REASONING to revise draft
    """
    # Merge Axi + Claude audit recommendations
    all_recommendations = list(recommendations or [])
    if audit_recommendations:
        all_recommendations += audit_recommendations
        log.info(f"[IMPROVE] Merged {len(recommendations)} Axi + {len(audit_recommendations)} Claude audit recs → {len(all_recommendations)} total")
    else:
        log.info(f"[IMPROVE] Applying {len(all_recommendations)} recommendations...")

    if external_standards is None:
        external_standards = {"standards": [], "content": {}}

    # Build improvement prompt with standards context
    external_standards_section = ""
    if external_standards["standards"]:
        external_standards_section = "\n\nEXTERNAL STANDARDS TO INTEGRATE:"
        for std, content in external_standards["content"].items():
            external_standards_section += f"\n\n{std}:\n{content[:800]}"

    improvement_prompt = f"""Improve the following document by integrating all recommendations and external standards.

TOPIC: {topic}

RECOMMENDATIONS (Axi + Claude audit teacher):
{chr(10).join(f"- {r}" for r in all_recommendations)}{external_standards_section}

CURRENT DOCUMENT (FULL — do not lose any existing sections):
{doc_text}

CRITICAL IMPROVEMENT RULES:
1. PRESERVE all existing Markdown headings (##, ###) — do NOT remove or rename sections
2. EXTEND sections by adding content under them, never replace structure
3. ADD all recommended new sections as new ## headings at the end
4. Integrate external standards content into relevant existing sections
5. Expand References section with all new standards found
6. Output the COMPLETE improved document — every section, not a summary

Generate the fully improved document:"""

    try:
        log.info(f"[IMPROVE] Calling {ModelConfig.SLOT120_REASONING} for revision...")
        generated = _slot120_generate(improvement_prompt, timeout=180, num_predict=5000)
        log.info(
            "[IMPROVE] Document improved (%d chars, model=%s)",
            len(generated),
            ModelConfig.SLOT120_REASONING,
        )
        return generated
    except TimeoutError:
        log.error(f"[IMPROVE] Improvement timeout (>10 min)")
    except Exception as e:
        log.error(f"[IMPROVE] Failed: {e}")

    log.warning(f"[IMPROVE] Falling back to original document")
    return doc_text  # Return original if improvement fails


# ──────────────────────────────────────────────────────────────────────────────
# TRAINING PAIR EXPORT — Self-Learning for FT Pipeline
# ──────────────────────────────────────────────────────────────────────────────

def _save_training_pairs(
    cycle: int,
    topic: str,
    doc_text: str,
    metrics: GenerationMetrics,
    recommendations: list[str],
    external_standards: dict,
    output_dir: Path,
) -> None:
    """
    Save training pairs from this cycle for continuous fine-tuning.

    Three types of training pairs:
    1. Generation pair: topic + internal_standards → draft (input: Omi's search + generation)
    2. Improvement pair: draft + recommendations → improved_draft (input: Axi's validation)
    3. Quality evaluation pair: document → quality assessment (meta-learning)

    Pairs are saved inside the run output directory for traceable Traini ingestion.
    """
    if metrics.overall_score < 0.60:
        # Skip low-quality documents
        log.debug(f"[TRAIN] Skipping cycle {cycle}: quality too low ({metrics.overall_score:.1%})")
        return

    # Keep each run self-contained. The legacy global directory can be root-owned.
    ft_dir = output_dir / "learning_pairs"
    ft_dir.mkdir(parents=True, exist_ok=True)

    # Training pair 1: Generation pair (Omi's work)
    # Input: topic + internal standards found
    # Output: generated draft
    if metrics.overall_score >= 0.70:
        generation_pair = {
            "type": "generation",
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "topic": topic,
            "input_prompt": f"Generate comprehensive document on: {topic}",
            "internal_standards": [],  # Would come from Omi search
            "output_draft": doc_text[:2000],  # First 2000 chars
            "quality_score": metrics.overall_score,
            "model": ModelConfig.SLOT120_REASONING
        }

        # Append to generation pairs
        gen_pairs_path = ft_dir / "generation_pairs.jsonl"
        with open(gen_pairs_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(generation_pair, ensure_ascii=False) + "\n")
        log.info(f"[TRAIN] Saved generation pair (cycle {cycle}, quality={metrics.overall_score:.1%})")

    # Training pair 2: Improvement pair (Axi's work)
    # Input: current draft + recommendations
    # Output: improved draft (to be generated in next cycle)
    if recommendations and metrics.overall_score >= 0.70:
        improvement_pair = {
            "type": "improvement",
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "topic": topic,
            "current_draft": doc_text[:1500],
            "recommendations": recommendations[:5],  # Top 5 recommendations
            "external_standards": external_standards.get('standards', [])[:5],
            "quality_before": metrics.overall_score,
            "structure_score": metrics.structure_score,
            "standards_score": metrics.standards_score,
            "model": "claude_code_cli_aws:opus-4.6"
        }

        # Append to improvement pairs
        imp_pairs_path = ft_dir / "improvement_pairs.jsonl"
        with open(imp_pairs_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(improvement_pair, ensure_ascii=False) + "\n")
        log.info(f"[TRAIN] Saved improvement pair (cycle {cycle}, {len(recommendations)} recommendations)")

    # Training pair 3: Quality evaluation pair (meta-learning)
    # Input: document
    # Output: quality assessment (structure, standards, coverage scores)
    if metrics.overall_score >= 0.75:
        quality_pair = {
            "type": "quality_evaluation",
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
            "topic": topic,
            "document_excerpt": doc_text[:1000],
            "assessment": {
                "structure_score": metrics.structure_score,
                "standards_score": metrics.standards_score,
                "coverage_score": metrics.coverage_score,
                "overall_score": metrics.overall_score,
            },
            "sections_found": metrics.sections_found,
            "sections_expected": metrics.sections_expected,
            "standards_found": metrics.standards_found,
            "standards_expected": metrics.standards_expected,
        }

        # Append to quality pairs
        qual_pairs_path = ft_dir / "quality_assessment_pairs.jsonl"
        with open(qual_pairs_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(quality_pair, ensure_ascii=False) + "\n")
        log.info(f"[TRAIN] Saved quality assessment pair (cycle {cycle})")

    log.info(f"[TRAIN] Training pairs for cycle {cycle} exported to {ft_dir}")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

def run_cyclic_generation(
    topic: str,
    reference_pdf: Path,
    max_cycles: int = 5,
    target_quality: float = 0.95,
    output_dir: Path = None,
) -> CycleResult:
    """
    Run complete cyclic generation pipeline:
    Omi draft → Eval → Axi validate → Improve → Repeat until target quality
    """
    if output_dir is None:
        output_dir = Path("aims_workspace/cyclic_doc_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    preflight = _runtime_preflight(output_dir)
    judge_smoke = _claude_judge_smoke(output_dir)
    teacher_judge_model = judge_smoke["model"]
    routed_topic = _slot14_route_topic(topic, output_dir)
    log.info(
        "[PREFLIGHT] PASS slot14=%s slot120=%s projected_vram=%.1f%%",
        ModelConfig.SLOT14_SEARCH,
        ModelConfig.SLOT120_REASONING,
        preflight["projected_vram_fraction"] * 100,
    )

    # Load reference template — supports PDF and DOCX
    reference_text = ""
    if reference_pdf.exists():
        suffix = reference_pdf.suffix.lower()
        try:
            if suffix == ".docx":
                from docx import Document as DocxDocument
                docx = DocxDocument(str(reference_pdf))
                reference_text = "\n".join(
                    p.text for p in docx.paragraphs if p.text.strip()
                )
                log.info(f"[REF] Loaded reference docx: {len(reference_text)} chars, {len(docx.paragraphs)} paragraphs")
            else:
                import pdfplumber
                with pdfplumber.open(str(reference_pdf)) as pdf:
                    for page in pdf.pages:
                        ref_text = page.extract_text()
                        if ref_text:
                            reference_text += ref_text + "\n"
                log.info(f"[REF] Loaded reference PDF: {len(reference_text)} chars")
        except Exception as e:
            log.warning(f"Could not load reference document: {e}")

    best_result = None
    all_metrics = []
    external_standards_cache = {"standards": [], "content": {}}  # Accumulate across cycles
    repair_batch: list[str] = []
    recommendations: list[str] = []
    internal_standards: list[str] = []
    applied_recs_this_cycle: list[str] = []  # recs applied at START of cycle — verify these, not new ones
    prev_doc_text: str = ""  # previous cycle snapshot for lineage and fallback
    last_accepted_doc: str = ""
    last_accepted_metrics: Optional[GenerationMetrics] = None
    # Cycle runs until:
    # 1. Target quality reached (target_quality, default 0.95)
    # 2. Last 3 cycles changed < 0.01% (convergence stall)
    # 3. max_cycles > 0 hard limit reached
    # max_cycles=0 = unlimited
    NO_PROGRESS_LIMIT   = 3     # consecutive cycles with delta < 0.0001 → stop
    NO_PROGRESS_DELTA   = 0.001  # threshold: 0.1% delta = no meaningful progress

    cycle = 0
    no_progress_streak = 0
    while True:
        cycle += 1
        if max_cycles > 0 and cycle > max_cycles:
            log.info(f"[CYCLE {cycle}] max_cycles={max_cycles} hard limit reached — stopping")
            break

        log.info(f"\n{'='*70}")
        log.info(f"CYCLE {cycle}" + (f"/{max_cycles}" if max_cycles > 0 else " (unlimited)"))
        log.info(f"{'='*70}")

        cycle_dir = output_dir / f"cycle_{cycle:02d}"
        cycle_dir.mkdir(exist_ok=True)
        section_edit_result: Optional[dict] = None
        changes_applied_by_skill: list[str] = []
        applied_recs_this_cycle: list[str] = []

        # Load repair batch from previous cycle (if cycle > 1)
        if cycle > 1:
            prev_cycle_dir = output_dir / f"cycle_{cycle-1:02d}"
            prev_repair_plan = prev_cycle_dir / "repair_plan.json"
            if prev_repair_plan.exists():
                try:
                    with open(prev_repair_plan, 'r', encoding='utf-8') as f:
                        plan_data = json.load(f)
                        repair_batch = plan_data.get("selected", [])
                        log.info(f"[CYCLE {cycle}] Loaded {len(repair_batch)} recommendations from cycle {cycle-1}")
                except Exception as e:
                    log.warning(f"[CYCLE {cycle}] Failed to load repair plan from cycle {cycle-1}: {e}")
                    repair_batch = []
            else:
                log.warning(f"[CYCLE {cycle}] No repair plan found for cycle {cycle-1}")
                repair_batch = []

        # STAGE 1: Omi generates draft OR apply improvements
        if cycle == 1:
            # First cycle: Omi searches internal database automatically
            log.info(f"[CYCLE {cycle}] Omi generating initial draft...")
            raw_standards = _search_internal_standards(
                routed_topic,
                max_results=20,
            )
            # Filter out Qdrant noise (electrical/unrelated standards).
            # When reference_text is available, prefer standards cited in it.
            internal_standards = _filter_standards_for_reference(
                raw_standards, reference_text
            )
            generation_context = build_generation_context(
                topic=routed_topic,
                doc_type="policy",
                task_context=topic,
                standards=internal_standards,
                reference_text=reference_text,
                reference_path=str(reference_pdf),
            )
            write_context_manifest(
                generation_context,
                cycle_dir / "generation_context_manifest.json",
            )
            doc_text = _omi_generate_draft(
                routed_topic,
                reference_template=reference_text,
                standards_to_inject=internal_standards,
                search_internal=False,
                grounded_prompt=render_generation_prompt(generation_context),
            )
        else:
            # Track which recs we're applying — needed for lineage check after improvement
            all_recs = list(repair_batch)
            applied_recs_this_cycle = all_recs
            log.info(f"[CYCLE {cycle}] Applying {len(all_recs)} recommendations (targeted edits)...")

            # GAP-001: section-batched transactional editing
            section_edit_result = apply_section_edits(
                doc=doc_text,
                recommendations=all_recs,
                last_accepted_doc=last_accepted_doc or prev_doc_text,
                reference_text=reference_text,
            )
            doc_text = section_edit_result["improved_doc"]
            changes_applied_by_skill = section_edit_result[
                "verified_recommendations"
            ]
            log.info(
                f"[CYCLE {cycle}] Section edits: {len(changes_applied_by_skill)} verified, "
                f"global={len(section_edit_result['global_recs'])}, "
                f"unresolved={len(section_edit_result['unresolved_recs'])}, "
                f"rolled_back={section_edit_result['rolled_back']}"
            )
            if section_edit_result["unresolved_recs"]:
                log.warning(
                    f"[CYCLE {cycle}] Unresolved recs: "
                    f"{section_edit_result['unresolved_recs'][:2]}"
                )

        if not doc_text:
            log.error(f"[CYCLE {cycle}] Generation failed, stopping")
            break

        # ── Phase 2: inject Section 8 sub-element nesting stubs (no LLM) ────
        phase2_result = apply_phase2_nesting(doc_text)
        if phase2_result["sections_expanded"]:
            doc_text = phase2_result["improved_doc"]
            log.info(
                "[CYCLE %d] Phase 2 nesting: %s expanded, %d stubs added",
                cycle,
                phase2_result["sections_expanded"],
                phase2_result["total_stubs_added"],
            )
        else:
            log.debug(
                "[CYCLE %d] Phase 2 nesting: no new stubs needed (already_nested=%s)",
                cycle,
                phase2_result.get("already_nested", []),
            )

        # ── SKILL 1: validate_structure — catch stubs before eval ──────────
        struct_report = validate_structure(doc_text)
        if not struct_report.passed:
            log.warning(
                f"[CYCLE {cycle}] Structure incomplete "
                f"({struct_report.completeness_ratio:.0%}) — expanding {len(struct_report.stub_sections + struct_report.empty_sections)} stubs..."
            )
            standards_ctx = " | ".join(external_standards_cache.get("standards", []))
            doc_text, expanded = expand_stub_sections(
                doc_text, standards_ctx, topic, model=ModelConfig.SLOT120_REASONING
            )
            if expanded:
                log.info(f"[CYCLE {cycle}] Skill expanded sections: {expanded}")
                struct_report = validate_structure(doc_text)  # re-check
                log.info(f"[CYCLE {cycle}] Structure after expansion: {struct_report.completeness_ratio:.0%}")

        # STAGE 2: Evaluate quality
        log.info(f"[CYCLE {cycle}] Evaluating quality...")
        metrics = _evaluate_document_quality(doc_text, topic, reference_text)
        metrics.cycle = cycle
        # The detailed TOC/body validator is stricter than doc_quality_eval and
        # must cap the structural score. This prevents a 50% headline score
        # from hiding 29% actual completeness.
        metrics.structure_score = min(
            metrics.structure_score,
            struct_report.completeness_ratio,
        )
        metrics.section_coverage = metrics.structure_score
        metrics.overall_score = (
            metrics.structure_score
            + metrics.standards_score
            + metrics.coverage_score
        ) / 3.0

        # STAGE 3: One bounded Axi pass followed by one bounded Opus audit.
        # Avoid nested future/CLI timeouts and duplicate fallback calls.
        log.info(
            f"[CYCLE {cycle}] Running bounded Axi validation, external search, "
            "then Claude audit..."
        )
        audit_schema_passed = False
        audit_quality_passed = False
        audit_quality_failures: list[str] = []
        audit_result = None
        external_standards_cache = _search_external_standards(topic, doc_text)
        axi_feedback, recommendations = _axi_validate_and_recommend(
            doc_text,
            metrics,
            topic,
            reference_text,
            False,
        )
        log.info(
            f"[CYCLE {cycle}] Axi validation complete: "
            f"{len(recommendations)} recommendations"
        )
        log.info(
            f"[CYCLE {cycle}] External standards found: "
            f"{external_standards_cache['standards']}"
        )

        try:
            audit_result = _claude_code_audit(
                omi_standards=internal_standards,
                axi_standards=external_standards_cache.get("standards", []),
                doc_excerpt=doc_text,
                axi_recommendations=recommendations,
                topic=topic,
                reference_text=reference_text,
                cycle=cycle,
                structure_report={
                    "completeness_ratio": struct_report.completeness_ratio,
                    "stub_sections": struct_report.stub_sections,
                    "empty_sections": struct_report.empty_sections,
                },
                evidence_dir=cycle_dir,
                model=teacher_judge_model,
            )
            if audit_result:
                audit_schema_passed = True
                (
                    audit_quality_passed,
                    audit_quality_failures,
                ) = _evaluate_audit_quality(audit_result)
                log.info(
                    f"[CYCLE {cycle}] Claude audit teacher: "
                    f"{len(audit_result.recommendations_from_audit)} recs + "
                    f"{len(audit_result.skill_recommendations)} skill recs; "
                    f"quality={'PASS' if audit_quality_passed else 'BLOCK'}"
                )
                if audit_result.skill_recommendations:
                    skill_recs_path = cycle_dir / "skill_recommendations.json"
                    skill_recs_path.write_text(
                        json.dumps(
                            {
                                "cycle": cycle,
                                "skill_recommendations": (
                                    audit_result.skill_recommendations
                                ),
                                "reference_gap": audit_result.reference_gap,
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    log.info(
                        f"[CYCLE {cycle}] Skill recommendations saved to "
                        f"{skill_recs_path}"
                    )
        except Exception as exc:
            log.warning(f"[CYCLE {cycle}] Claude audit failed: {exc}")

        missing_section_recs = _missing_section_recommendations(
            (
                audit_result.reference_gap.get("missing_sections", [])
                if audit_result
                else []
            )
        )
        repair_plan = _build_repair_plan(
            recommendations,
            missing_section_recs + (
                audit_result.recommendations_from_audit
                if audit_result
                else []
            ),
            doc_text=doc_text,
        )
        repair_batch = repair_plan["selected"]
        (cycle_dir / "repair_plan.json").write_text(
            json.dumps(repair_plan, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(
            f"[CYCLE {cycle}] Next repair batch: "
            f"{repair_plan['selected_count']} selected across "
            f"{len(repair_plan['selected_targets'])} targets; "
            f"{repair_plan['deferred_count']} deferred"
        )

        metrics.axi_recommendations = recommendations

        draft_path = cycle_dir / "draft.md"
        draft_path.write_text(doc_text, encoding='utf-8')

        # ── SKILL 3: quality_gate — evaluate BEFORE learning pairs ─────────
        gate = quality_gate(
            structure_score=metrics.structure_score,
            standards_score=metrics.standards_score,
            overall_score=metrics.overall_score,
        )
        log.info(f"[CYCLE {cycle}] Quality gate: {gate.reason}")

        # ── Rollback: reject candidate if structure regressed ───────────────
        baseline_metrics = last_accepted_metrics or (
            all_metrics[-1] if all_metrics else None
        )
        structure_regressed = bool(
            baseline_metrics
            and metrics.structure_score < baseline_metrics.structure_score - 0.001
        )
        overall_regressed = bool(
            baseline_metrics
            and metrics.overall_score < baseline_metrics.overall_score - 0.001
        )
        critical_regression = structure_regressed or overall_regressed
        if critical_regression and (last_accepted_doc or prev_doc_text):
            log.warning(
                f"[CYCLE {cycle}] Critical regression detected "
                f"(structure={structure_regressed}, overall={overall_regressed}) "
                "— rolling back to last accepted draft"
            )
            rejected_path = cycle_dir / "draft_rejected.md"
            rejected_path.write_text(doc_text, encoding='utf-8')
            doc_text = last_accepted_doc or prev_doc_text
            draft_path.write_text(doc_text, encoding='utf-8')
            log.info(f"[CYCLE {cycle}] Rolled back. Rejected candidate archived to {rejected_path}")

        # ── SKILL 2: verify_recommendations — check lineage ─────────────────
        # IMPORTANT: verify the recs that were APPLIED at start of cycle (applied_recs),
        # not the new recs generated by Axi this cycle.
        changes_applied: list[str] = list(changes_applied_by_skill)
        rec_lineage_passed = cycle == 1
        if cycle > 1 and prev_doc_text and applied_recs_this_cycle:
            rec_verify = verify_recommendations(applied_recs_this_cycle, prev_doc_text, doc_text)
            log.info(
                f"[CYCLE {cycle}] Rec lineage: apply_rate={rec_verify.apply_rate:.0%} "
                f"(applied={len(rec_verify.applied)}, partial={len(rec_verify.partial)}, "
                f"skipped={len(rec_verify.skipped)}/{len(applied_recs_this_cycle)})"
            )
            pending_global = bool(
                section_edit_result
                and section_edit_result["global_recs"]
            )
            pending_unresolved = bool(
                section_edit_result
                and section_edit_result["unresolved_recs"]
            )
            # Only flag global rollback (entire doc reverted to last_accepted_draft).
            # Individual section partial-commits are expected — unverified recs
            # surface in skipped[] and re-enter the next audit cycle.
            section_rollback = bool(
                section_edit_result
                and section_edit_result["rolled_back"]
            )
            rec_lineage_passed = (
                rec_verify.passed
                and bool(changes_applied)
                and not pending_global
                and not pending_unresolved
                and not section_rollback
            )
            if rec_verify.skipped:
                log.info(f"[CYCLE {cycle}] Skipped recs re-injected: {rec_verify.skipped[:3]}")
                # Re-inject skipped into next cycle's recommendations
                recommendations = rec_verify.skipped + recommendations

        metrics.changes_applied = changes_applied

        hard_gate_allowed, hard_gate_failures = _evaluate_cycle_hard_gate(
            gate=gate,
            struct_report=struct_report,
            audit_schema_passed=audit_schema_passed,
            audit_quality_passed=audit_quality_passed,
            audit_quality_failures=audit_quality_failures,
            rec_lineage_passed=rec_lineage_passed,
            critical_regression=critical_regression,
        )

        if hard_gate_allowed:
            last_accepted_doc = doc_text
            last_accepted_metrics = metrics

        prev_doc_text = doc_text
        all_metrics.append(metrics)

        metrics_path = cycle_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps(asdict(metrics), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Skills report (gate already computed above)
        skills_report = {
            "cycle": cycle,
            "structure": {
                "completeness_ratio": struct_report.completeness_ratio,
                "passed": struct_report.passed,
                "empty_sections": struct_report.empty_sections,
                "stub_sections": struct_report.stub_sections,
            },
            "quality_gate": {
                "allowed": gate.allowed,
                "reason": gate.reason,
                "scores": gate.scores,
            },
            "rollback": critical_regression,
            "audit_schema_passed": audit_schema_passed,
            "audit_quality_passed": audit_quality_passed,
            "audit_quality_failures": audit_quality_failures,
            "recommendation_lineage_passed": rec_lineage_passed,
            "hard_gate_allowed": hard_gate_allowed,
            "hard_gate_failures": hard_gate_failures,
            "changes_applied": changes_applied,
        }
        (cycle_dir / "skills_report.json").write_text(
            json.dumps(skills_report, indent=2, ensure_ascii=False), encoding='utf-8'
        )

        # Save as DOCX — SKILL-15: Delivery Format Skill
        try:
            from ops.docagent.docx_writer import markdown_to_docx, verify_docx_quality
            docx_path = cycle_dir / f"document_cycle_{cycle:02d}.docx"
            markdown_to_docx(
                md_text=doc_text,
                output_path=docx_path,
                document_number="IMS-OPS-AIMS-PFM",
                title=topic,
                revision=str(cycle).zfill(2),
            )
            # Verify DOCX quality
            docx_qa = verify_docx_quality(docx_path)
            log.info(
                f"[CYCLE {cycle}] DOCX quality: {docx_qa['score']}/10 "
                f"({'PASS' if docx_qa['passed'] else 'FAIL'}) "
                f"issues={len(docx_qa['issues'])}"
            )
            if docx_qa["issues"]:
                log.warning(f"[CYCLE {cycle}] DOCX issues: {docx_qa['issues']}")
            (cycle_dir / "docx_quality.json").write_text(
                json.dumps(docx_qa, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            log.warning(f"[CYCLE {cycle}] DOCX save failed: {e}")

        # Symlink latest → current cycle
        latest = output_dir / "latest"
        if latest.is_symlink():
            latest.unlink()
        latest.symlink_to(cycle_dir.name)

        # Save training pairs ONLY if quality gate allows
        training_tag = None
        if hard_gate_allowed:
            _save_training_pairs(
                cycle=cycle,
                topic=topic,
                doc_text=doc_text,
                metrics=metrics,
                recommendations=recommendations,
                external_standards=external_standards_cache,
                output_dir=output_dir
            )
        else:
            reason = "; ".join(hard_gate_failures)
            training_tag = f"INVALID_FOR_TRAINING:{reason}"
            log.warning(f"[CYCLE {cycle}] Learning pairs BLOCKED: {training_tag}")
            # Write quarantine marker so data is traceable but not used
            (cycle_dir / "training_quarantine.json").write_text(
                json.dumps(
                    {
                        "cycle": cycle,
                        "reason": training_tag,
                        "scores": gate.scores,
                        "detailed_structure": struct_report.completeness_ratio,
                        "audit_schema_passed": audit_schema_passed,
                        "audit_quality_passed": audit_quality_passed,
                        "audit_quality_failures": audit_quality_failures,
                        "recommendation_lineage_passed": rec_lineage_passed,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        log.info(f"[CYCLE {cycle}] Draft: {draft_path}")
        log.info(f"[CYCLE {cycle}] Quality: overall={metrics.overall_score:.1%}, structure={metrics.structure_score:.1%}, standards={metrics.standards_score:.1%}")
        log.info(f"[CYCLE {cycle}] Axi feedback: {axi_feedback[:200]}")

        # Progress tracking
        prev_score = all_metrics[-2].overall_score if len(all_metrics) >= 2 else 0.0
        delta = metrics.overall_score - prev_score
        if abs(delta) < NO_PROGRESS_DELTA:
            no_progress_streak += 1
            log.info(
                f"[CYCLE {cycle}] Δ={delta:+.4f} < threshold={NO_PROGRESS_DELTA} "
                f"— stall streak {no_progress_streak}/{NO_PROGRESS_LIMIT}"
            )
        else:
            no_progress_streak = 0
            log.info(f"[CYCLE {cycle}] Progress Δ={delta:+.4f} ({delta:+.2%})")

        best_result = CycleResult(
            cycle_num=cycle,
            success=(
                metrics.overall_score >= target_quality
                and hard_gate_allowed
            ),
            generated_doc_path=draft_path,
            metrics=metrics,
            axi_feedback=axi_feedback,
            ready_for_next_cycle=True,
            convergence_score=metrics.overall_score,
            bedrock_invoked=audit_result.bedrock_invoked if audit_result else False,
        )

        # Check convergence
        if metrics.overall_score >= target_quality and hard_gate_allowed:
            log.info(f"[CYCLE {cycle}] TARGET QUALITY REACHED: {metrics.overall_score:.1%}")
            best_result.ready_for_next_cycle = False
            break

        if no_progress_streak >= NO_PROGRESS_LIMIT:
            log.warning(
                f"[CYCLE {cycle}] CONVERGENCE STALL — last {NO_PROGRESS_LIMIT} cycles "
                f"delta < {NO_PROGRESS_DELTA:.1%}. Stopping. "
                f"Check cycle_dir/skill_recommendations.json for skill improvement proposals."
            )
            best_result.ready_for_next_cycle = False
            break

        log.info(f"[CYCLE {cycle}] Continuing... (quality={metrics.overall_score:.1%}, target={target_quality:.1%})")

    # Save summary
    summary = {
        "topic": topic,
        "routed_topic": routed_topic,
        "models": {
            "slot14": ModelConfig.SLOT14_SEARCH,
            "slot120": ModelConfig.SLOT120_REASONING,
        },
        "teacher_judge": {
            "provider": "claude_code_cli_aws",
            "slot120_used_as_teacher": False,
            "slot120_used_as_judge": False,
            "teacher_model": f"claude_code_cli_aws:{teacher_judge_model}",
            "judge_model": f"claude_code_cli_aws:{teacher_judge_model}",
            "degraded_mode": judge_smoke.get("degraded_mode", False),
        },
        "cycles_completed": len(all_metrics),
        "target_quality": target_quality,
        "status": (
            "TARGET_REACHED"
            if best_result and best_result.success
            else "INCOMPLETE"
            if best_result
            else "FAIL_GENERATION"
        ),
        "achieved_quality": best_result.metrics.overall_score if best_result else 0.0,
        "convergence_trajectory": [m.overall_score for m in all_metrics],
        "final_output": str(best_result.generated_doc_path) if best_result else None,
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')

    if best_result is None:
        log.error("PIPELINE FAILED: no document was generated")
        raise RuntimeError("No document generated")

    log.info(f"\n{'='*70}")
    log.info(f"PIPELINE COMPLETE")
    log.info(f"Cycles: {len(all_metrics)}, Quality: {best_result.metrics.overall_score:.1%}, Output: {output_dir}")
    log.info(f"{'='*70}\n")

    return best_result


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(description="Cyclic document generation pipeline")
    parser.add_argument("--topic", default="Asset Integrity Management Policy and Framework", help="Document topic")
    parser.add_argument("--reference-pdf", type=Path, default=Path("/media/axi_omi_sphere/FDF0-25E2/Documents/Block 10/Стандарты/IG7894~I/Asset Integrity Management Policy and Framework (AIM-PFM).pdf"), help="Reference template PDF")
    parser.add_argument("--max-cycles", type=int, default=5, help="Maximum cycles")
    parser.add_argument("--target-quality", type=float, default=0.95, help="Target quality score (0-1)")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")

    args = parser.parse_args()

    result = run_cyclic_generation(
        topic=args.topic,
        reference_pdf=args.reference_pdf,
        max_cycles=args.max_cycles,
        target_quality=args.target_quality,
        output_dir=args.output_dir,
    )

    print(f"\n✓ Pipeline result: {'SUCCESS' if result.success else 'INCOMPLETE'}")
    print(f"  Final quality: {result.convergence_score:.1%}")
    print(f"  Output: {result.generated_doc_path}")
