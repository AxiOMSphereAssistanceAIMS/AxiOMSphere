#!/usr/bin/env python3
"""Strict action-based eval for AIMS FT models.

Modes
-----
Standard (always):
  For each case, call the eval model, extract the "action" field, compare to
  expected_action → binary pass/fail.

LLM-judge (optional, --judge=nim|anthropic|ollama):
  After the binary check, call a judge model with the rubric from the test case
  and ask it to score the full response (0.0–1.0) and leave a comment.
  Requires --judge-api-key (or env var) for cloud judges.

Eval backend (--eval-backend):
  ollama     (default) — POST to /api/chat on --ollama-url
  anthropic  — POST to Anthropic-compatible /v1/messages; use --eval-base-url
               to point at a proxy (e.g. Omnirouter on http://localhost:8082)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── eval model call ────────────────────────────────────────────────────────────

def _chat(base_url: str, model: str, messages: list[dict[str, Any]], timeout: float) -> str:
    """Ollama /api/chat backend."""
    url = base_url.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str((payload.get("message") or {}).get("content") or "")


def _chat_anthropic(
    base_url: str, api_key: str, model: str, messages: list[dict[str, Any]], timeout: float
) -> str:
    """Anthropic-compatible /v1/messages backend (direct API or local proxy)."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": 1024,
        "messages": user_msgs,
    }
    if system:
        body["system"] = system
    url = (base_url.rstrip("/") + "/v1/messages") if base_url else "https://api.anthropic.com/v1/messages"
    if base_url:
        auth_headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    else:
        auth_headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **auth_headers}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload.get("content") or []
    return str(content[0].get("text") or "") if content else ""


def _extract_action(text: str) -> str:
    if not text.strip():
        return ""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return str(obj.get("action") or "").strip()
        except json.JSONDecodeError:
            pass
    m2 = re.search(r'"action"\s*:\s*"([^"]+)"', text)
    if m2:
        return m2.group(1).strip()
    return ""


# ── LLM-judge ─────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "You are a strict evaluator for an AI document-management assistant. "
    "You will receive the user's request, the expected action, a rubric with "
    "evaluation criteria, and the model's actual output. "
    "Return ONLY a JSON object — no markdown, no text outside the JSON."
)

_JUDGE_USER_TMPL = """\
USER MESSAGE:
{user_msg}

EXPECTED ACTION: {expected_action}

RUBRIC (evaluation criteria):
{rubric}

MODEL OUTPUT:
{model_output}

Evaluate the model output against the rubric.
Return a single JSON object with exactly these keys:
  "score"   : float 0.0–1.0  (0.0 = completely wrong, 0.5 = partially correct, 1.0 = fully correct)
  "pass"    : bool            (true if score >= 0.7)
  "comment" : string          (1–2 sentences explaining why)
"""


def _build_judge_messages(
    user_msg: str, model_output: str, expected_action: str, rubric: str
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": _JUDGE_USER_TMPL.format(
                user_msg=user_msg[:800],
                expected_action=expected_action,
                rubric=rubric[:600],
                model_output=model_output[:1200],
            ),
        },
    ]


def _extract_judge(text: str) -> dict[str, Any]:
    """Parse judge JSON from LLM response; graceful on failure."""
    m = re.search(r"\{[^{}]*\"score\"[^{}]*\}", text, re.S)
    if not m:
        m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = float(obj.get("score", 0))
            score = round(min(1.0, max(0.0, score)), 3)
            return {
                "judge_score": score,
                "judge_pass": bool(obj.get("pass", score >= 0.7)),
                "judge_comment": str(obj.get("comment", ""))[:600],
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return {
        "judge_score": None,
        "judge_pass": None,
        "judge_comment": f"parse_error: {text[:300]}",
    }


def _judge_call_ollama(
    base_url: str, model: str, messages: list[dict], timeout: float
) -> str:
    url = base_url.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str((payload.get("message") or {}).get("content") or "")


def _judge_call_nim(api_key: str, model: str, messages: list[dict], timeout: float) -> str:
    """Call NVIDIA NIM judge via Anthropic-compatible /v1/chat/completions API."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    body: dict[str, Any] = {
        "model": model,
        "messages": user_msgs,
        "temperature": 0,
        "max_tokens": 512,
    }
    if system:
        body["messages"].insert(0, {"role": "system", "content": system})
    nim_url = os.environ.get("NVIDIA_NIM_URL", "http://127.0.0.1:8082").rstrip("/")
    url = f"{nim_url}/v1/chat/completions"
    auth_headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **auth_headers}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return str(
        (choices[0].get("message") or {}).get("content", "")
    )


def _judge_call_anthropic(
    api_key: str, model: str, messages: list[dict], timeout: float, base_url: str = ""
) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [m for m in messages if m["role"] != "system"]
    body = {
        "model": model,
        "max_tokens": 512,
        "system": system,
        "messages": user_msgs,
    }
    # When routing via a local proxy (e.g. Omnirouter on port 8082) the proxy
    # uses "Authorization: Bearer <token>" instead of "x-api-key".
    if base_url:
        url = base_url.rstrip("/") + "/v1/messages"
        auth_headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    else:
        url = "https://api.anthropic.com/v1/messages"
        auth_headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", **auth_headers}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload.get("content") or []
    return str(content[0].get("text") or "") if content else ""


def _run_judge(
    backend: str,
    judge_model: str,
    judge_url: str,
    api_key: str,
    messages: list[dict],
    timeout: float,
    judge_base_url: str = "",
) -> str:
    if backend == "ollama":
        return _judge_call_ollama(judge_url, judge_model, messages, timeout)
    if backend == "nim":
        return _judge_call_nim(api_key, judge_model, messages, timeout)
    if backend == "anthropic":
        return _judge_call_anthropic(api_key, judge_model, messages, timeout, base_url=judge_base_url)
    raise ValueError(f"Unknown judge backend: {backend!r}")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    # eval model args
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout-sec", type=float, default=90.0)
    ap.add_argument(
        "--eval-backend",
        choices=["ollama", "anthropic"],
        default="ollama",
        help="Backend for the eval model: ollama (default) or anthropic-compatible",
    )
    ap.add_argument(
        "--eval-base-url",
        default="",
        help="Base URL for anthropic eval backend (e.g. http://localhost:8082 for Omnirouter)",
    )
    ap.add_argument(
        "--eval-api-key",
        default="",
        help="API key for anthropic eval backend (overrides ANTHROPIC_API_KEY env var)",
    )
    # judge args
    ap.add_argument(
        "--judge",
        choices=["none", "nim", "anthropic", "ollama"],
        default="none",
        help="LLM-judge backend (default: none — binary action-match only)",
    )
    ap.add_argument(
        "--judge-model",
        default="",
        help=(
            "Judge model name. Defaults: nim=meta/llama-3.1-405b-instruct, "
            "anthropic=claude-haiku-4-5-20251001, ollama=qwen3:14b"
        ),
    )
    ap.add_argument(
        "--judge-url",
        default="http://127.0.0.1:11434",
        help="Ollama base URL for judge (only used when --judge=ollama)",
    )
    ap.add_argument(
        "--judge-api-key",
        default="",
        help="API key for cloud judge (overrides env vars NVIDIA_NIM_API_KEY / ANTHROPIC_API_KEY)",
    )
    ap.add_argument(
        "--judge-base-url",
        default="",
        help=(
            "Override base URL for anthropic judge backend "
            "(e.g. http://localhost:8082 to route via Omnirouter). "
            "If empty, uses https://api.anthropic.com"
        ),
    )
    ap.add_argument("--judge-timeout-sec", type=float, default=60.0)
    args = ap.parse_args()

    # Resolve defaults for judge model
    _judge_model_defaults = {
        "nim": "meta/llama-3.1-405b-instruct",
        "anthropic": "claude-haiku-4-5-20251001",
        "ollama": "qwen3:14b",
    }
    judge_model = args.judge_model or _judge_model_defaults.get(args.judge, "")

    # Resolve API key from env if not provided
    judge_api_key = args.judge_api_key
    if not judge_api_key and args.judge == "nim":
        judge_api_key = os.environ.get("NVIDIA_NIM_API_KEY") or ""
    if not judge_api_key and args.judge == "anthropic":
        judge_api_key = os.environ.get("ANTHROPIC_API_KEY") or ""

    if args.judge != "none":
        if args.judge in ("nim", "anthropic") and not judge_api_key:
            print(f"WARNING: --judge={args.judge} but no API key found. Judge step will be skipped.")
            args.judge = "none"
        else:
            base_tag = f"  base={args.judge_base_url}" if args.judge_base_url else ""
            print(f"Judge: {args.judge} / {judge_model}{base_tag}")

    # Resolve API key for anthropic eval backend
    eval_api_key = args.eval_api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    if args.eval_backend == "anthropic":
        eval_base_tag = f"  base={args.eval_base_url}" if args.eval_base_url else ""
        print(f"Eval backend: anthropic / {args.model}{eval_base_tag}")
        if not eval_api_key:
            raise SystemExit("ERROR: --eval-backend=anthropic requires --eval-api-key or ANTHROPIC_API_KEY")

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    cases = suite.get("cases", [])
    results: list[dict[str, Any]] = []
    passed = 0
    judge_passed = 0
    judge_score_sum = 0.0
    judge_score_count = 0

    for idx, case in enumerate(cases):
        cid = str(case.get("id") or "case")
        expected = str(case.get("expected_action") or "").strip()
        rubric = str(case.get("rubric") or "").strip()
        messages = case.get("messages") or []
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")

        # ── step 1: eval model ─────────────────────────────────────────────────
        t0 = time.time()
        raw = ""
        err = ""
        try:
            if args.eval_backend == "anthropic":
                raw = _chat_anthropic(
                    args.eval_base_url, eval_api_key, args.model, messages, args.timeout_sec
                )
            else:
                raw = _chat(args.ollama_url, args.model, messages, args.timeout_sec)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        got = _extract_action(raw)
        ok = got == expected
        if ok:
            passed += 1
        elapsed_ms = int((time.time() - t0) * 1000)

        row: dict[str, Any] = {
            "id": cid,
            "expected": expected,
            "got": got,
            "pass": ok,
            "ms": elapsed_ms,
            "error": err,
            "raw": raw[:1500],
        }

        # ── step 2: LLM-judge ──────────────────────────────────────────────────
        if args.judge != "none":
            judge_result: dict[str, Any] = {
                "judge_score": None,
                "judge_pass": None,
                "judge_comment": "",
                "judge_raw": "",
            }
            if not rubric:
                judge_result["judge_comment"] = "no_rubric"
            else:
                try:
                    judge_msgs = _build_judge_messages(user_msg, raw, expected, rubric)
                    jt0 = time.time()
                    judge_text = _run_judge(
                        args.judge,
                        judge_model,
                        args.judge_url,
                        judge_api_key,
                        judge_msgs,
                        args.judge_timeout_sec,
                        judge_base_url=args.judge_base_url,
                    )
                    judge_result = _extract_judge(judge_text)
                    judge_result["judge_raw"] = judge_text[:600]
                    judge_result["judge_ms"] = int((time.time() - jt0) * 1000)
                except Exception as e:  # noqa: BLE001
                    judge_result["judge_comment"] = f"judge_error: {e}"

            if judge_result.get("judge_pass"):
                judge_passed += 1
            if judge_result.get("judge_score") is not None:
                judge_score_sum += judge_result["judge_score"]
                judge_score_count += 1

            row.update(judge_result)

        results.append(row)
        status = "✓" if ok else "✗"
        judge_tag = ""
        if args.judge != "none" and row.get("judge_score") is not None:
            judge_tag = f"  judge={row['judge_score']:.2f}"
        print(f"  [{idx+1:>3}/{len(cases)}] {status} {cid:<45}{judge_tag}")

    total = len(results)
    report: dict[str, Any] = {
        "model": args.model,
        "passed": passed,
        "total": total,
        "pass_rate": round((passed / total), 3) if total else 0.0,
    }
    if args.judge != "none":
        report["judge_backend"] = args.judge
        report["judge_model"] = judge_model
        report["judge_passed"] = judge_passed
        report["judge_pass_rate"] = round(judge_passed / total, 3) if total else None
        report["judge_avg_score"] = (
            round(judge_score_sum / judge_score_count, 3) if judge_score_count else None
        )
    report["cases"] = results

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{total} passed ({round(100 * report['pass_rate'])}%) [action-match]")
    if args.judge != "none":
        print(
            f"{judge_passed}/{total} passed ({round(100 * (report['judge_pass_rate'] or 0))}%) [judge] "
            f"  avg_score={report['judge_avg_score']}"
        )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
