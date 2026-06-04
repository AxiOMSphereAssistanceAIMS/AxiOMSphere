#!/usr/bin/env python3
"""Claude Code review backend invocation helpers.

Supports:
- simulation (handled by the worker)
- real_local_claude_cli
- aws_bedrock_claude_code

The real routes use the local `claude` CLI with Bedrock env enabled.
This module records a local usage ledger and redacts command details.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logi.claude_review_transport_policy import (
    get_blocked_models,
    get_claude_review_model_alias,
    validate_real_bedrock_env,
)


LEDGER_PATH = Path("aims_workspace/aws_bedrock_usage_ledger/bedrock_claude_calls.jsonl")


@dataclass
class ClaudeBackendInvocation:
    review_id: str
    source_agent: str
    route: str
    model: str
    review_mode: str
    provider: str
    model_requested: str
    model_effective: str
    aws_profile: str
    aws_region: str
    region: str
    bedrock_enabled: bool
    claude_code_called: bool
    simulation_used: bool
    command_redacted: list[str]
    stdout_excerpt: str
    stderr_excerpt: str
    returncode: int
    status: str
    prompt_chars: int
    max_tokens: int
    estimated_cost_unknown_or_pending: str = "pending"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _excerpt(text: str, limit: int = 2000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if not candidate:
        raise ValueError("empty response")
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("response did not contain a JSON object")
    parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("parsed review result is not a JSON object")
    return parsed


def build_bedrock_claude_command(
    *,
    prompt: str,
    model_alias: str,
    max_tokens: int,
    use_dangerous_skip_permissions: bool = True,
) -> list[str]:
    """Build the local Claude Code CLI command."""
    cmd = ["claude", "--print", "--model", model_alias]
    if use_dangerous_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.append(prompt)
    return cmd


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    # Ensure the CLI sees the explicit Bedrock route when requested.
    env.setdefault("CLAUDE_CODE_USE_BEDROCK", "1")
    return env


def invoke_real_claude_review(
    *,
    review_id: str,
    review_mode: str,
    prompt: str,
    max_tokens: int = 1024,
    prefer_heavy: bool = False,
    require_bedrock_env: bool = True,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Invoke the local Claude Code CLI against the configured backend."""
    if timeout_seconds is None:
        raw_timeout = os.environ.get("AIMS_CLAUDE_REVIEW_TIMEOUT_SECONDS", "").strip()
        timeout_seconds = int(raw_timeout) if raw_timeout.isdigit() else 300

    env_check = validate_real_bedrock_env(review_mode)
    if require_bedrock_env and not env_check["ok"]:
        raise RuntimeError("; ".join(env_check["errors"]))

    model_requested = get_claude_review_model_alias(prefer_heavy=prefer_heavy)
    model_effective = env_check["model_effective"] or model_requested
    blocked_models = get_blocked_models()
    if model_effective in blocked_models:
        raise RuntimeError(f"blocked model requested: {model_effective}")

    cmd = build_bedrock_claude_command(
        prompt=prompt,
        model_alias=model_requested,
        max_tokens=max_tokens,
        use_dangerous_skip_permissions=True,
    )

    proc = subprocess.run(
        cmd,
        env=_runtime_env(),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )

    invocation = ClaudeBackendInvocation(
        timestamp=datetime.now(timezone.utc).isoformat(),
        source_agent="logi",
        review_id=review_id,
        route=review_mode,
        model=model_requested,
        review_mode=review_mode,
        provider=review_mode,
        model_requested=model_requested,
        model_effective=model_effective,
        aws_profile=env_check["aws_profile"],
        aws_region=env_check["aws_region"],
        region=env_check["aws_region"],
        bedrock_enabled=env_check["bedrock_enabled"],
        claude_code_called=True,
        simulation_used=False,
        command_redacted=[
            "claude",
            "--print",
            "--model",
            model_requested,
            "--dangerously-skip-permissions",
            "<prompt omitted>",
        ],
        stdout_excerpt=_excerpt(proc.stdout),
        stderr_excerpt=_excerpt(proc.stderr),
        returncode=proc.returncode,
        status="PASS" if proc.returncode == 0 else "FAIL",
        prompt_chars=len(prompt),
        max_tokens=max_tokens,
    )

    ledger_entry = invocation.to_dict()
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_entry, ensure_ascii=False) + "\n")

    if proc.returncode != 0:
        raise RuntimeError(f"claude_cli_failed: {proc.returncode}: {proc.stderr.strip()[:500]}")

    review = _extract_json_object(proc.stdout)
    review.update(
        {
            "review_id": review_id,
            "review_mode": review_mode,
            "provider": review_mode,
            "model_requested": model_requested,
            "model_effective": model_effective,
            "aws_profile": env_check["aws_profile"],
            "aws_region": env_check["aws_region"],
            "bedrock_enabled": env_check["bedrock_enabled"],
            "claude_code_called": True,
            "simulation_used": False,
            "command_redacted": invocation.command_redacted,
            "stdout_excerpt": invocation.stdout_excerpt,
            "stderr_excerpt": invocation.stderr_excerpt,
            "execution_allowed": False,
        }
    )
    return review


def build_bedrock_review_ledger_sample() -> dict[str, Any]:
    """Return the latest ledger sample, if any, without secrets."""
    if not LEDGER_PATH.exists():
        return {}
    lines = LEDGER_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except Exception:
        return {}


__all__ = [
    "LEDGER_PATH",
    "build_bedrock_claude_command",
    "build_bedrock_review_ledger_sample",
    "invoke_real_claude_review",
]
