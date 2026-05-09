#!/usr/bin/env python3
"""Generate training pairs from failed eval cases (Phase 6 self-learning loop).

For each failed case in an eval result JSON, calls the NIM teacher model to
produce a correct assistant response, then saves the pair to JSONL.

Usage:
    python3 ops/ft/scripts/auto_pair.py \
        --eval-file ops/ft/logs/eval_14_v16_golden_v2.json \
        --out ops/ft/data/auto_pairs/pairs_YYYYMMDD.jsonl

    python3 ops/ft/scripts/auto_pair.py \
        --eval-file ops/ft/logs/eval_14_v16_golden_v2.json \
        --dry-run

Pipeline:
    eval_fail → NIM teacher (Nemotron-Ultra-253B) → JSON pair → JSONL
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime

try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from nim_client import NIMClient, TEACHER_MODEL
except ImportError as e:
    print(f"ERROR: {e} — run from aims-workspace", file=sys.stderr)
    sys.exit(1)

_SYSTEM_PROMPT = (
    "You are Omi — AIMS document registry archiver. "
    "Always respond with a single JSON object only. "
    "Respond ONLY with a JSON object using one of these actions: "
    "classify_doc, find_duplicates, reassign_doc, create_master, "
    "generate_report, search, clarify, handoff_axi, answer"
)

_TEACHER_SYSTEM = (
    "You are generating training data for an AIMS document archiver named Omi. "
    "Given a user message and the expected action, produce the ideal JSON response "
    "that Omi would give. Output ONLY valid JSON, no explanation."
)


def _load_env() -> None:
    if os.environ.get("OMNIROUTE_BASE_URL") or os.environ.get("NVIDIA_API_KEY"):
        return
    env_file = pathlib.Path(__file__).resolve().parents[3] / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _load_failed_cases(eval_file: str) -> list[dict]:
    with open(eval_file, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", data.get("results", []))
    failed = [r for r in cases if not r.get("pass", False)]
    print(f"Loaded {len(cases)} cases, {len(failed)} failed")
    return failed


def _enrich_from_suite(failed: list[dict], suite_path: str) -> list[dict]:
    """Join eval result cases with golden_v2 suite to add messages + expected_action."""
    try:
        with open(suite_path, encoding="utf-8") as f:
            suite = json.load(f)
        suite_by_id = {c["id"]: c for c in suite.get("cases", [])}
    except Exception as e:
        print(f"  warn: could not load suite {suite_path}: {e}", file=sys.stderr)
        return failed
    enriched = []
    for case in failed:
        cid = case.get("id", "")
        base = suite_by_id.get(cid, {})
        merged = {**base, **case}
        # Normalise key: eval result uses "expected", suite uses "expected_action"
        if "expected_action" not in merged and merged.get("expected"):
            merged["expected_action"] = merged["expected"]
        enriched.append(merged)
    return enriched


def _generate_pair(
    client: NIMClient,
    case: dict,
    dry_run: bool = False,
) -> dict | None:
    messages = case.get("messages", [])
    expected_action = case.get("expected_action", "")
    user_msg = next(
        (m["content"] for m in messages if m["role"] == "user"),
        case.get("user", ""),
    )
    if not user_msg:
        return None

    if dry_run:
        return {
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": json.dumps(
                    {"action": expected_action, "dry_run": True}
                )},
            ],
            "source": "auto_pair/dry_run",
            "case_id": case.get("id", ""),
            "expected_action": expected_action,
        }

    teacher_prompt = (
        f"User message to Omi: {user_msg}\n\n"
        f"Expected action type: {expected_action}\n\n"
        f"Produce the ideal JSON response Omi should return for this message. "
        f"The JSON must contain 'action': '{expected_action}' and all relevant fields."
    )

    try:
        raw = client.chat(
            prompt=teacher_prompt,
            system=_TEACHER_SYSTEM,
            temperature=0.1,
            max_tokens=512,
        )
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        obj = json.loads(raw[start:end])
        if obj.get("action") != expected_action:
            obj["action"] = expected_action
    except (json.JSONDecodeError, Exception) as e:
        print(f"  warn case={case.get('id', '?')}: {e}", file=sys.stderr)
        return None

    return {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)},
        ],
        "source": f"auto_pair/{TEACHER_MODEL}",
        "case_id": case.get("id", ""),
        "expected_action": expected_action,
        "generated_at": datetime.utcnow().isoformat(),
    }


def main() -> None:
    _default_suite = str(pathlib.Path(__file__).parent.parent / "eval" / "golden_v2.json")
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-file", required=True, help="Path to eval result JSON")
    ap.add_argument("--suite", default=_default_suite, help="golden_v2 suite JSON for user-message lookup")
    ap.add_argument("--out", default=None, help="Output JSONL path")
    ap.add_argument("--model", default=TEACHER_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.out is None:
        date_str = datetime.utcnow().strftime("%Y%m%d")
        out_dir = pathlib.Path(__file__).parent.parent / "data" / "auto_pairs"
        out_dir.mkdir(parents=True, exist_ok=True)
        args.out = str(out_dir / f"pairs_{date_str}.jsonl")

    failed = _load_failed_cases(args.eval_file)
    failed = _enrich_from_suite(failed, args.suite)
    if not failed:
        print("No failed cases — nothing to generate")
        return

    _load_env()
    api_key = os.environ.get("OMNIROUTE_API_KEY", "")
    omniroute_url = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")

    client = NIMClient(
        omniroute_url,
        api_key=api_key,
        timeout=180,
    )
    if not args.dry_run:
        client._default_model = args.model  # type: ignore[attr-defined]

    pairs = []
    for case in failed:
        pair = _generate_pair(client, case, dry_run=args.dry_run)
        if pair:
            pairs.append(pair)
            print(f"  generated pair for case={case.get('id', '?')}")
        if not args.dry_run:
            time.sleep(0.3)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"Done. Wrote {len(pairs)} pairs → {args.out}")


if __name__ == "__main__":
    main()
