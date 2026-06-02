#!/usr/bin/env python3
"""
AIMS Bedrock Auditor smoke wrapper.

Purpose:
- Verify DGX/local pipeline can invoke AWS Bedrock Claude auditor.
- Uses local secret env file, but never prints AWS keys.
- Produces a small JSON evidence file for audit logs.

Default env file:
  ~/.aims/secrets/aws_bedrock_auditor.env

Required env variables:
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_DEFAULT_REGION
  AIMS_BEDROCK_AUDITOR_MODEL
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any


DEFAULT_ENV_FILE = Path.home() / ".aims" / "secrets" / "aws_bedrock_auditor.env"
DEFAULT_PROMPT = "Return exactly: AIMS_BEDROCK_AUDITOR_OK"
EXPECTED_TEXT = "AIMS_BEDROCK_AUDITOR_OK"


def load_export_env(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")

    loaded: Dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # Handles quoted values safely.
        try:
            value = shlex.split(value)[0]
        except Exception:
            value = value.strip('"').strip("'")

        if key:
            loaded[key] = value

    return loaded


def redact_env_for_report(env: Dict[str, str]) -> Dict[str, str]:
    safe = {}
    for key, value in env.items():
        if key in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}:
            safe[key] = "***REDACTED***"
        else:
            safe[key] = value
    return safe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=80)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--out-dir",
        default="aims_workspace/bedrock_auditor/smoke_tests",
        help="Directory for JSON evidence output.",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    loaded_env = load_export_env(env_file)

    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
        "AIMS_BEDROCK_AUDITOR_MODEL",
    ]
    missing = [k for k in required if not loaded_env.get(k)]
    if missing:
        print(f"ERROR: missing required env keys: {missing}", file=sys.stderr)
        return 2

    run_env = os.environ.copy()
    run_env.update(loaded_env)

    region = loaded_env["AWS_DEFAULT_REGION"]
    model_id = loaded_env["AIMS_BEDROCK_AUDITOR_MODEL"]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": args.prompt,
                }
            ],
        }
    ]

    inference_config = {
        "maxTokens": args.max_tokens,
        "temperature": args.temperature,
    }

    cmd = [
        "aws",
        "bedrock-runtime",
        "converse",
        "--region",
        region,
        "--model-id",
        model_id,
        "--messages",
        json.dumps(messages, ensure_ascii=False),
        "--inference-config",
        json.dumps(inference_config),
    ]

    started = dt.datetime.now(dt.timezone.utc).isoformat()

    result: Dict[str, Any] = {
        "run_type": "aims_bedrock_auditor_smoke",
        "started_utc": started,
        "region": region,
        "model_id": model_id,
        "prompt": args.prompt,
        "expected_text": EXPECTED_TEXT,
        "env_file": str(env_file),
        "env_redacted": redact_env_for_report(loaded_env),
        "command_redacted": [
            x if not x.startswith("AWS_") else "***REDACTED***" for x in cmd
        ],
    }

    try:
        proc = subprocess.run(
            cmd,
            env=run_env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result.update(
            {
                "status": "FAIL",
                "error": "timeout",
                "details": str(exc),
            }
        )
        return write_result(result, args.out_dir, exit_code=3)

    result["returncode"] = proc.returncode

    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()

    if proc.returncode != 0:
        result.update(
            {
                "status": "FAIL",
                "error": "aws_cli_failed",
                "stdout": proc.stdout.strip(),
            }
        )
        return write_result(result, args.out_dir, exit_code=proc.returncode or 1)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result.update(
            {
                "status": "FAIL",
                "error": "invalid_json_from_aws_cli",
                "stdout": proc.stdout.strip(),
            }
        )
        return write_result(result, args.out_dir, exit_code=4)

    content = payload.get("output", {}).get("message", {}).get("content", [])
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
    answer_text = "\n".join(t for t in text_parts if t).strip()

    usage = payload.get("usage", {})
    metrics = payload.get("metrics", {})

    status = "PASS" if answer_text == EXPECTED_TEXT else "WARN"

    result.update(
        {
            "status": status,
            "answer_text": answer_text,
            "usage": usage,
            "metrics": metrics,
            "raw_response": payload,
            "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )

    return write_result(result, args.out_dir, exit_code=0 if status == "PASS" else 5)


def write_result(result: Dict[str, Any], out_dir: str, exit_code: int) -> int:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_path = out_path / f"aims_bedrock_auditor_smoke_{stamp}.json"

    file_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "status": result.get("status"),
        "region": result.get("region"),
        "model_id": result.get("model_id"),
        "answer_text": result.get("answer_text"),
        "usage": result.get("usage"),
        "metrics": result.get("metrics"),
        "evidence_file": str(file_path),
    }, indent=2, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
