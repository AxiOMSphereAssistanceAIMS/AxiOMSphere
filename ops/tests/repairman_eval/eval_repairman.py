"""AIMS Repairman Evaluation — runs all challenges through Claude Code and scores responses.

Usage:
    # Run all challenges
    python3 ops/tests/repairman_eval/eval_repairman.py

    # Run single challenge
    python3 ops/tests/repairman_eval/eval_repairman.py --challenge c02

    # Run with a specific model via gateway
    AIMS_EVAL_MODEL=aims-repairman-nemotron python3 ...
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
_CHALLENGES_DIR = _EVAL_DIR / "challenges"
_REPO_ROOT = _EVAL_DIR.parents[3]
_REPAIRMAN_SCRIPT = _REPO_ROOT / "ops" / "claude_code" / "run_repairman.sh"
_REPAIRMAN_ENV = _REPO_ROOT / "ops" / "claude_code" / "env.repairman"

CHALLENGES = [
    "c01_timeout_chain",
    "c02_preview_truncation",
    "c03_env_var_chain",
    "c04_silent_failure_omi",
    "c05_agent_dependency_graph",
    "c06_training_loop_trigger",
]

# Keywords the evaluator looks for in responses (heuristic scoring)
SCORING_HINTS: dict[str, list[tuple[int, list[str]]]] = {
    "c01_timeout_chain": [
        (20, ["tool_registry.py", "timeout_s", "doci_compose"]),
        (25, ["call_tool", "httpx", "compose_and_generate"]),
        (15, ["single float", "connect", "read timeout", "all timeout"]),
        (20, ["_generate_ollama", "ollama.*timeout", "doc_agent.*timeout"]),
        (20, ["diff", "---", "+++"]),
    ],
    "c02_preview_truncation": [
        (25, ["preview[:800]", "preview[:", "800"]),
        (25, ["orchestrator", "document_text", "preview"]),
        (20, ["doc_path", "docx", "full document"]),
        (20, ["_resolve_document_text", "read.*docx", "path.open", "doc_path"]),
        (10, ["diff", "---", "+++"]),
    ],
    "c03_env_var_chain": [
        (20, ["DOC_AGENT_OLLAMA_BASE", "DGX_OLLAMA_URL", "OLLAMA_BASE_URL", "priority"]),
        (25, ["ollama_resolve", "http://ollama:11434", "fallback"]),
        (15, ["KNOMI_OLLAMA_URL", "knomi_agent", "irrelevant", "not used"]),
        (25, ["localhost", "127.0.0.1", "hardcode", "safety"]),
        (15, ["docker", "host", "minimal"]),
    ],
    "c04_silent_failure_omi": [
        (30, ["discarded", "return value", "ignored", "call_tool.*result"]),
        (20, ["tool_registry", "error.*key", '{"error"']),
        (15, ["omi_agent", "8008", "response"]),
        (25, ["omi_result", "if.*error.*omi", "diff", "---"]),
        (10, ["error", "warning", "justify", "reliability"]),
    ],
    "c05_agent_dependency_graph": [
        (20, ["8001", "8002", "8003", "8004", "8005", "8006", "8007", "8008"]),
        (15, ["step 1", "step 2", "knomi", "blocked"]),
        (15, ["context_filter", "0.*docs", "empty", "filtered"]),
        (20, ["omi_search", "knomi_search", "schema", "result"]),
        (30, ["poli_check", "restart_container", "mainy_execute", "audit_id"]),
    ],
    "c06_training_loop_trigger": [
        (25, ["check_training", "never called", "not called", "missing caller"]),
        (20, ["schedule.yaml", "aims_scheduler", "no.*cron", "missing"]),
        (15, ["argus_agent", "health.*event", "does not", "no.*training"]),
        (30, ["cron", "scheduler", "argus.*check_training", "wiring", "diff"]),
        (10, ["traini_agent", "trigger_ft", "fine.tun"]),
    ],
}


def _score_response(challenge_id: str, response: str) -> tuple[int, dict]:
    hints = SCORING_HINTS.get(challenge_id, [])
    details = {}
    total = 0
    resp_lower = response.lower()
    for points, keywords in hints:
        import re
        hit = any(re.search(kw.lower(), resp_lower) for kw in keywords)
        earned = points if hit else 0
        total += earned
        details["|".join(keywords[:2])] = f"{earned}/{points}"
    return total, details


def _run_challenge(challenge_id: str) -> tuple[int, str, dict]:
    challenge_file = _CHALLENGES_DIR / f"{challenge_id}.md"
    if not challenge_file.exists():
        return 0, f"challenge file not found: {challenge_file}", {}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tf:
        tf.write(challenge_file.read_text())
        issue_path = tf.name

    env = os.environ.copy()
    env_file_path = _REPAIRMAN_ENV
    if env_file_path.exists():
        for line in env_file_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')

    try:
        result = subprocess.run(
            ["bash", str(_REPAIRMAN_SCRIPT), str(_REPO_ROOT), issue_path],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        response = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        response = "TIMEOUT: repairman did not respond within 300s"
    finally:
        Path(issue_path).unlink(missing_ok=True)

    score, breakdown = _score_response(challenge_id, response)
    return score, response, breakdown


def main():
    parser = argparse.ArgumentParser(description="AIMS Repairman Evaluation")
    parser.add_argument("--challenge", default=None, help="Run single challenge (e.g. c02)")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    args = parser.parse_args()

    targets = CHALLENGES
    if args.challenge:
        targets = [c for c in CHALLENGES if c.startswith(args.challenge)]
        if not targets:
            print(f"No challenge matching '{args.challenge}'")
            sys.exit(1)

    results = {}
    for cid in targets:
        print(f"\n{'='*60}")
        print(f"Running challenge: {cid}")
        print("="*60)
        score, response, breakdown = _run_challenge(cid)
        results[cid] = {"score": score, "max": 100, "breakdown": breakdown}
        if not args.json:
            print(f"\n--- Response (first 2000 chars) ---")
            print(response[:2000])
            print(f"\n--- Score: {score}/100 ---")
            for k, v in breakdown.items():
                print(f"  {k}: {v}")

    total = sum(r["score"] for r in results.values())
    max_total = len(results) * 100
    grade = "PASS" if total >= max_total * 0.7 else "FAIL"

    print(f"\n{'='*60}")
    print(f"FINAL: {total}/{max_total} ({100*total//max_total}%) — {grade}")
    print("="*60)
    for cid, r in results.items():
        print(f"  {cid}: {r['score']}/100")

    if args.json:
        print(json.dumps(results, indent=2))

    sys.exit(0 if grade == "PASS" else 1)


if __name__ == "__main__":
    main()
