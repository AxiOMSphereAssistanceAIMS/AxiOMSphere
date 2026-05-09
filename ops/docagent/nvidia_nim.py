#!/usr/bin/env python3
"""
OmniRoute client — quality gate and training pair generation.

Replaces NIM/Gemini as cloud quality backend in the local→cloud quality loop:
  local model → OmniRoute score → ≥85% match = master doc / <85% = training pair

Primary model: gemini-free-fallback (via OmniRoute at 127.0.0.1:20128)
API: OpenAI-compatible, http://127.0.0.1:20128/v1
Key env: OMNIROUTE_API_KEY (optional — OmniRoute is local, no key required)

Legacy fallback: set NVIDIA_API_KEY + NVIDIA_NIM_BASE_URL to re-enable direct NIM.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("docagent.nvidia_nim")

# OmniRoute: local OpenAI-compatible gateway to cloud reference models
OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1").rstrip("/")
DEFAULT_SCORE_MODEL = os.environ.get("OMNIROUTE_MODEL", "gemini-free-fallback")
FALLBACK_SCORE_MODEL = DEFAULT_SCORE_MODEL  # OmniRoute handles internal fallback

# Teacher combo model aliases — env-driven with fallback to DEFAULT_SCORE_MODEL
EXTRACT_MODEL  = os.environ.get("OMNIROUTE_EXTRACT_MODEL",  DEFAULT_SCORE_MODEL)
EXPERT_MODEL   = os.environ.get("OMNIROUTE_EXPERT_MODEL",   DEFAULT_SCORE_MODEL)
TEACHER_MODEL  = os.environ.get("OMNIROUTE_TEACHER_MODEL",  DEFAULT_SCORE_MODEL)
AUDIT_MODEL    = os.environ.get("OMNIROUTE_AUDIT_MODEL",    DEFAULT_SCORE_MODEL)

# Shadow audit: log audit result alongside pair save without blocking write
_SHADOW_AUDIT = os.environ.get("AIMS_AUDIT_PAIRS_SHADOW", "0") == "1"

# Legacy alias kept for backward compat — OMNIROUTE_BASE_URL takes precedence
NVIDIA_API_BASE = OMNIROUTE_BASE_URL

QUALITY_PAIRS_DIR = Path(os.environ.get(
    "QUALITY_PAIRS_DIR",
    "/home/axi_omi_sphere/aims-workspace/aims_workspace/training/quality_pairs",
))


def _api_key() -> str:
    # OmniRoute is local — key optional; falls back to legacy NVIDIA_API_KEY if set
    return (
        os.environ.get("OMNIROUTE_API_KEY", "").strip()
        or os.environ.get("NVIDIA_API_KEY", "").strip()
    )


def _chat(
    messages: list[dict],
    *,
    model: str = DEFAULT_SCORE_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: int = 90,
) -> str:
    key = _api_key()
    headers: dict = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OMNIROUTE_BASE_URL}/chat/completions",
        data=body,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"empty choices in response: {list(data.keys())}")
    return (choices[0].get("message") or {}).get("content", "").strip()


def score(
    user_request: str,
    document_text: str,
    model: str = DEFAULT_SCORE_MODEL,
) -> tuple[float, str]:
    """
    Score document quality against user request using NVIDIA NIM.
    Returns (score 0.0-1.0, feedback string).
    Returns (0.0, reason) when NIM is unavailable — callers must handle this explicitly.
    """
    # OmniRoute is local — no key required; proceed even without key

    prompt = (
        "Score this industrial document against the user request and applicable standards. "
        "Respond with ONLY a JSON object — no markdown, no explanation.\n\n"
        f"USER REQUEST: {user_request}\n\n"
        f"DOCUMENT (first 3000 chars):\n{document_text[:3000]}\n\n"
        'Output exactly: {"score": <float 0.0-1.0>, "feedback": "<one sentence>"}\n'
        "Score: 0.0=completely missing required content, 1.0=fully compliant. "
        "Criteria: ISO 45001, API RP, ASME, IEC, HSE best practices."
    )
    messages = [
        {"role": "system", "content": "You are a document quality evaluator. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    models_to_try = [model]
    if model != FALLBACK_SCORE_MODEL:
        models_to_try.append(FALLBACK_SCORE_MODEL)

    last_err: Exception | None = None
    for m in models_to_try:
        try:
            text = _chat(messages, model=m, temperature=0.1, max_tokens=256, timeout=60)
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
                if not match:
                    raise ValueError(f"no JSON in response: {text[:120]}")
                result = json.loads(match.group())
            s = float(result.get("score", 0.0))
            if not 0.0 <= s <= 1.0:
                raise ValueError(f"score out of range: {s}")
            log.info("omniroute: scored %.2f (model=%s)", s, m)
            return s, result.get("feedback", "")
        except Exception as e:
            log.warning("omniroute: score failed (model=%s): %s", m, e)
            last_err = e

    return 0.0, f"omniroute_failed: all models failed: {last_err}"


def generate_reference(
    prompt: str,
    domain: str = "oil_gas",
    model: str = DEFAULT_SCORE_MODEL,
    max_tokens: int = 4096,
    timeout: int = 180,
) -> str:
    """
    Generate a high-quality reference answer using OmniRoute reference model.
    Used as the 'chosen' output in training pairs when local score < 85%.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a world-class technical documentation specialist for industrial facilities "
                f"({domain} domain). "
                "Produce complete, standards-compliant documents (ISO 45001, API RP, ASME, IEC). "
                "Write in clear, precise English with numbered sections."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    return _chat(messages, model=model, temperature=0.2, max_tokens=max_tokens, timeout=timeout)


def save_quality_pair(
    prompt: str,
    local_output: str,
    cloud_output: str,
    pair_score: float,
    domain: str = "oil_gas",
) -> Path:
    """
    Save a (local, cloud) training pair for the quality loop.
    pair_score >= 0.85 → gold (master doc, both outputs usable)
    pair_score <  0.85 → dpo (local = rejected, cloud = chosen)
    """
    QUALITY_PAIRS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    pid = hashlib.md5(prompt[:100].encode()).hexdigest()[:8]
    pair_type = "gold" if pair_score >= 0.85 else "dpo"
    path = QUALITY_PAIRS_DIR / f"{pair_type}_{domain}_{ts}_{pid}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "prompt": prompt,
            "local": local_output,
            "cloud": cloud_output,
            "score": pair_score,
            "domain": domain,
            "type": pair_type,
            "cloud_model": f"omniroute:{DEFAULT_SCORE_MODEL}",
        }, f, ensure_ascii=False, indent=2)
    log.info("omniroute: saved %s pair → %s", pair_type, path.name)

    if _SHADOW_AUDIT:
        _shadow_audit_pair(path, prompt, local_output, cloud_output, pair_score, domain)

    return path


def _shadow_audit_pair(
    pair_path: Path,
    prompt: str,
    local_output: str,
    cloud_output: str,
    pair_score: float,
    domain: str,
) -> None:
    """Shadow-mode audit: call AUDIT_MODEL and log result alongside the pair.

    Never blocks or raises — failures are logged and silently dropped.
    AIMS_AUDIT_PAIRS_SHADOW=1 enables this path.
    """
    audit_prompt = (
        "Audit this training pair for factual accuracy and source grounding.\n"
        "Respond with only a JSON object: "
        '{"verdict": "pass"|"flag", "confidence": <float 0-1>, "reason": "<one sentence>"}\n\n'
        f"PROMPT: {prompt[:500]}\n\n"
        f"LOCAL OUTPUT (rejected): {local_output[:800]}\n\n"
        f"CLOUD OUTPUT (chosen): {cloud_output[:800]}"
    )
    messages = [
        {"role": "system", "content": "You are a training data auditor. Output only valid JSON."},
        {"role": "user", "content": audit_prompt},
    ]
    audit_result: dict = {}
    try:
        raw = _chat(messages, model=AUDIT_MODEL, temperature=0.0, max_tokens=128, timeout=30)
        try:
            audit_result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            audit_result = json.loads(m.group()) if m else {"raw": raw}
    except Exception as e:
        log.debug("shadow_audit: call failed (model=%s): %s", AUDIT_MODEL, e)
        audit_result = {"error": str(e)}

    sidecar = pair_path.with_name(pair_path.stem + "_audit.json")
    try:
        with sidecar.open("w", encoding="utf-8") as f:
            json.dump({
                "pair_file": pair_path.name,
                "audit_model": AUDIT_MODEL,
                "pair_score": pair_score,
                "domain": domain,
                **audit_result,
            }, f, ensure_ascii=False, indent=2)
        log.debug("shadow_audit: wrote sidecar → %s", sidecar.name)
    except Exception as e:
        log.debug("shadow_audit: sidecar write failed: %s", e)


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    question = " ".join(sys.argv[1:]) or "What are the key requirements of ISO 45001 for confined space entry?"
    doc = "This JSA covers confined space entry. Workers must wear PPE. Supervisor must be present."
    s, fb = score(question, doc)
    print(f"score={s:.2f}  feedback={fb}")
