#!/usr/bin/env python3
"""Smoke test for OmniRoute teacher combo model availability.

Sends a minimal ping to each of the 4 teacher combo models and prints
a result table. Does NOT start any tuning or heavy processing.

Usage:
    python ops/learning/smoke_teacher_combos.py
    OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1 python ops/learning/smoke_teacher_combos.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = (
    os.environ.get("OMNIROUTE_BASE_URL")
    or os.environ.get("AIMS_OMNIROUTE_BASE_URL")
    or "http://127.0.0.1:20128/v1"
).rstrip("/")

TIMEOUT_SEC = 60

MODELS = [
    "doc-extract-combo",
    "doc-standard-expert-combo",
    "doc-training-standards-best",
    "doc-training-pair-audit-combo",
]

PING_PROMPT = "Reply only: OK"


def _ping(model: str) -> tuple[bool, str, str]:
    """Returns (ok, actual_model, error_or_empty)."""
    key = os.environ.get("OMNIROUTE_API_KEY", "").strip()
    headers: dict = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PING_PROMPT}],
        "max_tokens": 16,
        "temperature": 0.0,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            data = json.load(r)
        actual = (data.get("model") or model)
        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        return True, actual, content
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()[:120]
        except Exception:
            pass
        return False, model, f"HTTP {e.code}: {body_text}"
    except Exception as e:
        return False, model, str(e)[:120]


def main() -> None:
    print(f"\nOmniRoute smoke test — base_url: {BASE_URL}")
    print(f"Timeout: {TIMEOUT_SEC}s per model\n")

    col_w = 35
    print(f"{'requested_model':<{col_w}} {'actual_model':<{col_w}} {'ok':<6} {'error / response'}")
    print("-" * 110)

    all_ok = True
    for model in MODELS:
        ok, actual, detail = _ping(model)
        if not ok:
            all_ok = False
        status = "YES" if ok else "NO"
        trunc_detail = detail[:50] if len(detail) > 50 else detail
        print(f"{model:<{col_w}} {actual:<{col_w}} {status:<6} {trunc_detail}")

    print()
    if all_ok:
        print("All 4 teacher combo models responded OK.")
    else:
        print("One or more models failed — check OmniRoute is running and models are registered.")
        sys.exit(1)


if __name__ == "__main__":
    main()
