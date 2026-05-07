#!/usr/bin/env python3
"""Document generation quality eval — IEC 61158 and similar suites.

Unlike eval_actions.py (which does binary action-match), this script:
  1. Sends suite-level system_prompt + per-case prompt to the eval model.
  2. Collects the full document text response (no JSON extraction).
  3. Runs an LLM judge against the per-case rubric (5 criteria, 0–1 each).
  4. Optionally enforces a min_words threshold.
  5. Writes a JSON report and prints a per-case + summary table.

Eval backends:
  ollama     (default) — POST to /api/chat on --ollama-url
  anthropic  — POST to /v1/messages; use --eval-base-url for local proxy

Judge backends:
  anthropic  (default) — real Anthropic API or proxy via --judge-base-url
  ollama     — local Ollama model
  nim        — NVIDIA NIM (Anthropic-compatible API)

Usage example (405b via Omnirouter as both eval model and judge):
  python -u ops/ft/scripts/eval_docgen.py \\
    --eval-backend anthropic \\
    --eval-base-url http://localhost:8082 \\
    --eval-api-key aims-local-repair-token \\
    --model llama-3.1-405b-instruct \\
    --judge anthropic \\
    --judge-model llama-3.1-405b-instruct \\
    --judge-base-url http://localhost:8082 \\
    --judge-api-key aims-local-repair-token \\
    --suite ops/ft/eval/docgen_iec61158.json \\
    --out ops/ft/logs/docgen_405b.json
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

# ── eval model ─────────────────────────────────────────────────────────────────

def _chat_ollama(
    base_url: str, model: str, system: str, user_prompt: str, timeout: float
) -> str:
    """Ollama /api/chat — returns full text response."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})
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


def _chat_anthropic(
    base_url: str, api_key: str, model: str, system: str, user_prompt: str,
    timeout: float, max_tokens: int = 4096
) -> str:
    """Anthropic-compatible /v1/messages (direct API or local proxy)."""
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if system:
        body["system"] = system
    if base_url:
        url = base_url.rstrip("/") + "/v1/messages"
        auth_headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    else:
        url = "https://api.anthropic.com/v1/messages"
        auth_headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **auth_headers},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload.get("content") or []
    return str(content[0].get("text") or "") if content else ""


# ── LLM judge ──────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "You are a strict technical documentation quality evaluator. "
    "You will receive a prompt describing what document to generate, "
    "a multi-criteria rubric, and the generated document text. "
    "Score ONLY based on the rubric. "
    "Return ONLY a JSON object — no markdown, no text outside the JSON."
)

_JUDGE_USER_TMPL = """\
DOCUMENT REQUEST:
{prompt}

RUBRIC (evaluation criteria):
{rubric}

GENERATED DOCUMENT ({word_count} words):
{document}

Evaluate the document strictly against each rubric criterion.
Return a single JSON object with exactly these keys:
  "score"    : float 0.0–1.0  (average across all criteria; 0.0 = fails all, 1.0 = meets all)
  "pass"     : bool            (true if score >= 0.70)
  "criteria" : list of floats  (one per rubric criterion, same order, each 0.0–1.0)
  "comment"  : string          (2–3 sentences summarising what is missing or well done)
"""


def _build_judge_messages(
    prompt: str, document: str, rubric: str, word_count: int
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": _JUDGE_USER_TMPL.format(
                prompt=prompt[:600],
                rubric=rubric[:1200],
                document=document[:3000],
                word_count=word_count,
            ),
        },
    ]


def _strip_json_comments(s: str) -> str:
    """Remove single-line comments (# ... and // ...) from inside JSON text."""
    lines = []
    for line in s.splitlines():
        # Remove trailing comment + its leading whitespace; preserve any comma before it
        cleaned = re.sub(r'\s*(#|//).*$', '', line)
        lines.append(cleaned)
    return "\n".join(lines)


def _extract_judge(text: str) -> dict[str, Any]:
    """Parse judge JSON; handles markdown fences and inline comments."""
    # strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        raw_json = m.group(0)
        for attempt in (raw_json, _strip_json_comments(raw_json)):
            try:
                obj = json.loads(attempt)
                score = float(obj.get("score", 0))
                score = round(min(1.0, max(0.0, score)), 3)
                criteria = obj.get("criteria") or []
                if isinstance(criteria, list):
                    criteria = [round(min(1.0, max(0.0, float(c))), 3) for c in criteria]
                return {
                    "judge_score": score,
                    "judge_pass": bool(obj.get("pass", score >= 0.70)),
                    "judge_criteria": criteria,
                    "judge_comment": str(obj.get("comment", ""))[:800],
                }
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    return {
        "judge_score": None,
        "judge_pass": None,
        "judge_criteria": [],
        "judge_comment": f"parse_error: {text[:300]}",
    }


def _run_judge(
    backend: str, judge_model: str, judge_url: str, api_key: str,
    messages: list[dict], timeout: float, judge_base_url: str = ""
) -> str:
    if backend == "ollama":
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        url = judge_url.rstrip("/") + "/api/chat"
        body = {
            "model": judge_model,
            "messages": ([{"role": "system", "content": system}] if system else []) + user_msgs,
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

    if backend == "nim":
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        body: dict[str, Any] = {
            "model": judge_model,
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
            url, data=data, headers={"Content-Type": "application/json", **auth_headers},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return str(
            (choices[0].get("message") or {}).get("content", "")
        )

    if backend == "anthropic":
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        body: dict[str, Any] = {
            "model": judge_model,
            "max_tokens": 512,
            "messages": user_msgs,
        }
        if system:
            body["system"] = system
        if judge_base_url:
            url = judge_base_url.rstrip("/") + "/v1/messages"
            auth_headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
        else:
            url = "https://api.anthropic.com/v1/messages"
            auth_headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json", **auth_headers},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload.get("content") or []
        return str(content[0].get("text") or "") if content else ""

    raise ValueError(f"Unknown judge backend: {backend!r}")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Eval document generation quality via LLM judge."
    )
    # eval model
    ap.add_argument("--model", required=True, help="Model name to evaluate")
    ap.add_argument("--suite", type=Path, required=True, help="Eval suite JSON file")
    ap.add_argument("--out", type=Path, required=True, help="Output JSON report path")
    ap.add_argument("--timeout-sec", type=float, default=180.0,
                    help="Timeout per doc generation call (default: 180s)")
    ap.add_argument(
        "--eval-backend", choices=["ollama", "anthropic"], default="ollama",
        help="Backend for eval model calls",
    )
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434",
                    help="Ollama base URL (used when --eval-backend=ollama)")
    ap.add_argument("--eval-base-url", default="",
                    help="Base URL for anthropic eval backend (e.g. http://localhost:8082)")
    ap.add_argument("--eval-api-key", default="",
                    help="API key for anthropic eval backend (overrides ANTHROPIC_API_KEY)")
    ap.add_argument("--max-tokens", type=int, default=4096,
                    help="Max tokens for document generation (default: 4096)")
    # judge
    ap.add_argument(
        "--judge", choices=["none", "anthropic", "ollama", "nim"],
        default="anthropic",
        help="Judge backend (default: anthropic)",
    )
    ap.add_argument("--judge-model", default="",
                    help="Judge model name (defaults per backend)")
    ap.add_argument("--judge-url", default="http://127.0.0.1:11434",
                    help="Ollama base URL for judge")
    ap.add_argument("--judge-base-url", default="",
                    help="Base URL for anthropic judge (e.g. http://localhost:8082)")
    ap.add_argument("--judge-api-key", default="",
                    help="API key for cloud judge")
    ap.add_argument("--judge-timeout-sec", type=float, default=180.0)
    # misc
    ap.add_argument("--smoke", action="store_true",
                    help="Run only first case (smoke test)")
    args = ap.parse_args()

    # Judge model defaults
    _judge_defaults = {
        "nim": "meta/llama-3.1-405b-instruct",
        "anthropic": "claude-haiku-4-5-20251001",
        "ollama": "qwen3:14b",
    }
    judge_model = args.judge_model or _judge_defaults.get(args.judge, "")

    # Resolve judge API key
    judge_api_key = args.judge_api_key
    if not judge_api_key and args.judge == "nim":
        judge_api_key = os.environ.get("NVIDIA_NIM_API_KEY") or ""
    if not judge_api_key and args.judge in ("anthropic",):
        judge_api_key = os.environ.get("ANTHROPIC_API_KEY") or ""

    if args.judge != "none":
        if args.judge in ("nim", "anthropic") and not judge_api_key:
            print(f"WARNING: --judge={args.judge} but no API key found. Judge disabled.")
            args.judge = "none"
        else:
            base_tag = f"  base={args.judge_base_url}" if args.judge_base_url else ""
            print(f"Judge: {args.judge} / {judge_model}{base_tag}")

    # Resolve eval API key
    eval_api_key = args.eval_api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    if args.eval_backend == "anthropic":
        base_tag = f"  base={args.eval_base_url}" if args.eval_base_url else ""
        print(f"Eval: anthropic / {args.model}{base_tag}")
        if not eval_api_key:
            raise SystemExit("ERROR: --eval-backend=anthropic requires --eval-api-key or ANTHROPIC_API_KEY")
    else:
        print(f"Eval: ollama / {args.model}  url={args.ollama_url}")

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    system_prompt: str = suite.get("system_prompt") or ""
    cases: list[dict] = suite.get("cases", [])

    if args.smoke:
        cases = cases[:1]
        print("Smoke mode: running 1 case only")

    results: list[dict[str, Any]] = []
    judge_score_sum = 0.0
    judge_score_count = 0
    judge_passed = 0

    for idx, case in enumerate(cases):
        cid = str(case.get("id") or f"case_{idx}")
        prompt = str(case.get("prompt") or "").strip()
        rubric = str(case.get("rubric") or "").strip()
        min_words: int = int(case.get("min_words") or 0)

        # ── step 1: generate document ──────────────────────────────────────────
        t0 = time.time()
        raw = ""
        err = ""
        try:
            if args.eval_backend == "anthropic":
                raw = _chat_anthropic(
                    args.eval_base_url, eval_api_key, args.model,
                    system_prompt, prompt, args.timeout_sec, args.max_tokens
                )
            else:
                raw = _chat_ollama(
                    args.ollama_url, args.model, system_prompt, prompt, args.timeout_sec
                )
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__

        elapsed_ms = int((time.time() - t0) * 1000)
        word_count = len(raw.split()) if raw else 0
        words_ok = (word_count >= min_words) if min_words else True

        row: dict[str, Any] = {
            "id": cid,
            "word_count": word_count,
            "min_words": min_words,
            "words_ok": words_ok,
            "ms": elapsed_ms,
            "error": err,
        }

        # ── step 2: judge ──────────────────────────────────────────────────────
        judge_result: dict[str, Any] = {
            "judge_score": None,
            "judge_pass": None,
            "judge_criteria": [],
            "judge_comment": "",
        }

        if args.judge != "none" and raw and not err:
            if not rubric:
                judge_result["judge_comment"] = "no_rubric"
            else:
                try:
                    judge_msgs = _build_judge_messages(prompt, raw, rubric, word_count)
                    jt0 = time.time()
                    judge_text = _run_judge(
                        args.judge, judge_model, args.judge_url, judge_api_key,
                        judge_msgs, args.judge_timeout_sec,
                        judge_base_url=args.judge_base_url,
                    )
                    judge_result = _extract_judge(judge_text)
                    judge_result["judge_ms"] = int((time.time() - jt0) * 1000)
                except Exception as e:  # noqa: BLE001
                    judge_result["judge_comment"] = f"judge_error: {e}"

        row.update(judge_result)
        row["raw"] = raw[:2000]  # truncated for report readability
        results.append(row)

        score = judge_result.get("judge_score")
        if score is not None:
            judge_score_sum += score
            judge_score_count += 1
            if judge_result.get("judge_pass"):
                judge_passed += 1

        # Print progress line
        words_tag = f"  {word_count}w" + ("" if words_ok else f"<{min_words}!")
        score_tag = f"  score={score:.2f}" if score is not None else ""
        pass_sym = "✓" if judge_result.get("judge_pass") else ("✗" if score is not None else "?")
        if err:
            pass_sym = "E"
        print(f"  [{idx+1:>3}/{len(cases)}] {pass_sym} {cid:<48}{words_tag}{score_tag}")

    # ── summary ────────────────────────────────────────────────────────────────
    total = len(results)
    avg_score = round(judge_score_sum / judge_score_count, 3) if judge_score_count else None

    report: dict[str, Any] = {
        "suite": str(args.suite),
        "model": args.model,
        "eval_backend": args.eval_backend,
        "judge_backend": args.judge,
        "judge_model": judge_model if args.judge != "none" else None,
        "total": total,
        "judge_passed": judge_passed,
        "judge_pass_rate": round(judge_passed / total, 3) if total else None,
        "judge_avg_score": avg_score,
        "cases": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'─'*60}")
    print(f"Model:       {args.model}")
    print(f"Cases:       {total}")
    if args.judge != "none":
        pct = round(100 * (report["judge_pass_rate"] or 0))
        print(f"Passed:      {judge_passed}/{total}  ({pct}%)  [judge >= 0.70]")
        print(f"Avg score:   {avg_score}")

        # Per-case score table
        print(f"\n{'ID':<50} {'score':>6}  {'words':>6}")
        print("─" * 66)
        for r in results:
            s = r.get("judge_score")
            score_str = f"{s:.2f}" if s is not None else " err"
            print(f"  {r['id']:<48} {score_str:>6}  {r['word_count']:>6}")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
