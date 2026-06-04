"""Shared policy for Claude Code review transport defaults."""

from __future__ import annotations

import os
from typing import Any, Dict

CLAUDE_CODE_AUTO_REVIEW_ENV = "AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW"
CLAUDE_CODE_AUTO_REVIEW_DEFAULT_ENABLED = True
AIMS_CLAUDE_REVIEW_PROVIDER_ENV = "AIMS_CLAUDE_REVIEW_PROVIDER"
AIMS_CLAUDE_REVIEW_DEFAULT_MODEL_ENV = "AIMS_CLAUDE_REVIEW_DEFAULT_MODEL"
AIMS_CLAUDE_REVIEW_HEAVY_MODEL_ENV = "AIMS_CLAUDE_REVIEW_HEAVY_MODEL"
AIMS_CLAUDE_REVIEW_ALLOW_OPUS_ENV = "AIMS_CLAUDE_REVIEW_ALLOW_OPUS"
AIMS_CLAUDE_REVIEW_BLOCKED_MODELS_ENV = "AIMS_CLAUDE_REVIEW_BLOCKED_MODELS"
AIMS_AWS_BEDROCK_BUDGET_GUARD_ENV = "AIMS_AWS_BEDROCK_BUDGET_GUARD"

DEFAULT_CLAUDE_REVIEW_PROVIDER = "simulation"
DEFAULT_CLAUDE_REVIEW_DEFAULT_MODEL = "sonnet"
DEFAULT_CLAUDE_REVIEW_HEAVY_MODEL = "opus"
DEFAULT_CLAUDE_REVIEW_BLOCKED_MODELS = "us.anthropic.claude-opus-4-7,us.anthropic.claude-opus-4-8"


def is_claude_code_auto_review_enabled() -> bool:
    """Return whether auto-review is enabled by default."""
    default_value = "1" if CLAUDE_CODE_AUTO_REVIEW_DEFAULT_ENABLED else "0"
    return os.environ.get(CLAUDE_CODE_AUTO_REVIEW_ENV, default_value).lower() in ("1", "true", "yes")


def get_claude_review_provider() -> str:
    """Return the selected review provider/mode."""
    provider = os.environ.get(AIMS_CLAUDE_REVIEW_PROVIDER_ENV, "").strip().lower()
    if provider:
        return provider

    if all(os.environ.get(key, "").strip() for key in ("AWS_PROFILE", "AWS_REGION", "CLAUDE_CODE_USE_BEDROCK")):
        return "aws_bedrock_claude_code"

    return DEFAULT_CLAUDE_REVIEW_PROVIDER


def get_claude_review_model_alias(prefer_heavy: bool = False) -> str:
    """Return the model alias to request from Claude Code."""
    if prefer_heavy and os.environ.get(AIMS_CLAUDE_REVIEW_ALLOW_OPUS_ENV, "0").lower() in ("1", "true", "yes"):
        return os.environ.get(AIMS_CLAUDE_REVIEW_HEAVY_MODEL_ENV, DEFAULT_CLAUDE_REVIEW_HEAVY_MODEL).strip() or DEFAULT_CLAUDE_REVIEW_HEAVY_MODEL
    return os.environ.get(AIMS_CLAUDE_REVIEW_DEFAULT_MODEL_ENV, DEFAULT_CLAUDE_REVIEW_DEFAULT_MODEL).strip() or DEFAULT_CLAUDE_REVIEW_DEFAULT_MODEL


def get_blocked_models() -> list[str]:
    """Return blocked model ids from env."""
    raw = os.environ.get(AIMS_CLAUDE_REVIEW_BLOCKED_MODELS_ENV, DEFAULT_CLAUDE_REVIEW_BLOCKED_MODELS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_bedrock_route_enabled() -> bool:
    """Return whether the Bedrock route has minimum env."""
    return all(os.environ.get(key, "").strip() for key in ("AWS_PROFILE", "AWS_REGION", "CLAUDE_CODE_USE_BEDROCK"))


def requires_bedrock_env(provider: str | None = None) -> bool:
    """Whether the selected provider must have Bedrock env."""
    return (provider or get_claude_review_provider()).strip().lower() == "aws_bedrock_claude_code"


def validate_real_bedrock_env(provider: str | None = None) -> Dict[str, Any]:
    """Validate the required environment for a real Bedrock-backed review."""
    provider_name = (provider or get_claude_review_provider()).strip().lower()
    aws_profile = os.environ.get("AWS_PROFILE", "").strip()
    aws_region = os.environ.get("AWS_REGION", "").strip()
    bedrock_enabled = os.environ.get("CLAUDE_CODE_USE_BEDROCK", "").strip().lower() in ("1", "true", "yes")
    model_alias = get_claude_review_model_alias()
    blocked_models = get_blocked_models()
    errors: list[str] = []

    if provider_name == "aws_bedrock_claude_code":
        if not aws_profile:
            errors.append("AWS_PROFILE missing")
        if not aws_region:
            errors.append("AWS_REGION missing")
        if not bedrock_enabled:
            errors.append("CLAUDE_CODE_USE_BEDROCK missing")

    model_env_name = "ANTHROPIC_DEFAULT_SONNET_MODEL" if model_alias == "sonnet" else "ANTHROPIC_DEFAULT_OPUS_MODEL"
    effective_model = os.environ.get(model_env_name, "").strip()
    if provider_name == "aws_bedrock_claude_code" and not effective_model:
        errors.append(f"{model_env_name} missing")
    if effective_model and effective_model in blocked_models:
        errors.append(f"blocked model requested: {effective_model}")

    return {
        "provider": provider_name,
        "aws_profile": aws_profile,
        "aws_region": aws_region,
        "bedrock_enabled": bedrock_enabled,
        "model_alias": model_alias,
        "model_effective": effective_model or model_alias,
        "blocked_models": blocked_models,
        "ok": len(errors) == 0,
        "errors": errors,
    }


__all__ = [
    "CLAUDE_CODE_AUTO_REVIEW_ENV",
    "CLAUDE_CODE_AUTO_REVIEW_DEFAULT_ENABLED",
    "AIMS_CLAUDE_REVIEW_PROVIDER_ENV",
    "AIMS_CLAUDE_REVIEW_DEFAULT_MODEL_ENV",
    "AIMS_CLAUDE_REVIEW_HEAVY_MODEL_ENV",
    "AIMS_CLAUDE_REVIEW_ALLOW_OPUS_ENV",
    "AIMS_CLAUDE_REVIEW_BLOCKED_MODELS_ENV",
    "AIMS_AWS_BEDROCK_BUDGET_GUARD_ENV",
    "DEFAULT_CLAUDE_REVIEW_PROVIDER",
    "DEFAULT_CLAUDE_REVIEW_DEFAULT_MODEL",
    "DEFAULT_CLAUDE_REVIEW_HEAVY_MODEL",
    "DEFAULT_CLAUDE_REVIEW_BLOCKED_MODELS",
    "is_claude_code_auto_review_enabled",
    "get_claude_review_provider",
    "get_claude_review_model_alias",
    "get_blocked_models",
    "is_bedrock_route_enabled",
    "requires_bedrock_env",
    "validate_real_bedrock_env",
]
