#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_MODELS = [
    # Поставь здесь ровно те модели, которые есть внутри doc-training-pair-audit-combo
    "claude-sonnet-4.5",
    "gemini-3-flash-preview",
    "qwen3.5-397b-a17b",
    "mistral-large-3-675b",
    "deepseek-v4-pro",
    "gpt-oss-120b",
    "nemotron-3-super:120b",
    "local-nemotron",
]


def normalize_base_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def call_model(base_url: str, model: str, timeout: int, prompt: str) -> dict:
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": 50,
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OMNIROUTE_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = time.monotonic() - started
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw)

            actual_model = body.get("model", "")
            content = (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            ok = bool(content.strip())
            return {
                "requested_model": model,
                "actual_model": actual_model,
                "ok": ok,
                "elapsed_sec": round(elapsed, 2),
                "status": resp.status,
                "response": content.strip()[:200],
                "error": "",
            }

    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - started
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(e)
        return {
            "requested_model": model,
            "actual_model": "",
            "ok": False,
            "elapsed_sec": round(elapsed, 2),
            "status": e.code,
            "response": "",
            "error": err_body[:300],
        }

    except TimeoutError:
        elapsed = time.monotonic() - started
        return {
            "requested_model": model,
            "actual_model": "",
            "ok": False,
            "elapsed_sec": round(elapsed, 2),
            "status": "",
            "response": "",
            "error": f"timeout after {timeout}s",
        }

    except Exception as e:
        elapsed = time.monotonic() - started
        return {
            "requested_model": model,
            "actual_model": "",
            "ok": False,
            "elapsed_sec": round(elapsed, 2),
            "status": "",
            "response": "",
            "error": f"{type(e).__name__}: {e}",
        }


def print_table(results: list[dict]) -> None:
    print()
    print(
        f"{'requested_model':36} {'actual_model':30} {'ok':5} "
        f"{'sec':>7} {'status':>8}  response/error"
    )
    print("-" * 120)

    for r in results:
        msg = r["response"] if r["ok"] else r["error"]
        print(
            f"{r['requested_model'][:36]:36} "
            f"{r['actual_model'][:30]:30} "
            f"{'YES' if r['ok'] else 'NO':5} "
            f"{r['elapsed_sec']:7.2f} "
            f"{str(r['status'])[:8]:>8}  "
            f"{msg}"
        )

    good = [r for r in results if r["ok"]]
    print()
    if good:
        print("Recommended order by response time among successful models:")
        for i, r in enumerate(sorted(good, key=lambda x: x["elapsed_sec"]), 1):
            print(
                f"{i:02d}. {r['requested_model']} "
                f"→ actual={r['actual_model']} "
                f"({r['elapsed_sec']}s)"
            )
    else:
        print("No successful models.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark individual candidate models for doc-training-pair-audit-combo."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "AIMS_OMNIROUTE_BASE_URL",
            os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1"),
        ),
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--prompt",
        default="Reply only: AUDIT_OK",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=DEFAULT_MODELS,
        help="Explicit list of model aliases to test.",
    )
    parser.add_argument(
        "--jsonl-out",
        default="aims_workspace/audit/audit_combo_model_benchmark.jsonl",
    )

    args = parser.parse_args()
    base_url = normalize_base_url(args.base_url)

    print(f"Audit combo candidate benchmark — base_url: {base_url}")
    print(f"Timeout: {args.timeout}s per model")
    print(f"Models: {len(args.models)}")
    print()

    results = []
    for model in args.models:
        print(f"Testing {model} ...", flush=True)
        result = call_model(base_url, model, args.timeout, args.prompt)
        result["tested_at"] = datetime.utcnow().isoformat() + "Z"
        result["base_url"] = base_url
        results.append(result)

    print_table(results)

    out_path = Path(args.jsonl_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"Saved JSONL results to: {out_path}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
