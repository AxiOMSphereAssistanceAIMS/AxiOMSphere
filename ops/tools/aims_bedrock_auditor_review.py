#!/usr/bin/env python3
"""
AIMS Bedrock Auditor review wrapper.

Purpose:
- Run an external quality audit through AWS Bedrock Claude.
- Accept text or an input file.
- Never print AWS secrets.
- Save structured JSON evidence for AIMS audit logs.
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


SYSTEM_INSTRUCTIONS = """You are an external quality auditor for AxiOMSphere / AIMS.

Your job is to review engineering outputs, code-change summaries, pipeline reports,
agent workflow plans, benchmark results, and release-gate materials.

Rules:
- Be evidence-based.
- Do not invent timestamps, files, test results, or approvals.
- If a timestamp/run_id is not provided, write "not_provided".
- Identify PASS/WARN/FAIL.
- Identify concrete risks and required controls.
- Highlight secret exposure risks.
- Be concise enough for an engineering audit log.
"""


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
        try:
            value = shlex.split(value)[0]
        except Exception:
            value = value.strip('"').strip("'")
        if key:
            loaded[key] = value
    return loaded


def read_input(args: argparse.Namespace) -> str:
    if args.input_file:
        path = Path(args.input_file)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8", errors="replace")

    if args.text:
        return args.text

    if not sys.stdin.isatty():
        return sys.stdin.read()

    raise ValueError("Provide --input-file, --text, or stdin input.")


def build_prompt(content: str, run_id: str, audit_type: str) -> str:
    return f"""Audit type: {audit_type}
Run ID: {run_id}
Timestamp UTC: {dt.datetime.now(dt.timezone.utc).isoformat()}

Review the following AIMS material.

Return exactly these sections:
1. VERDICT: PASS/WARN/FAIL
2. SUMMARY
3. MAIN RISKS
4. REQUIRED CONTROLS
5. SECRET/PRIVACY RISK
6. RECOMMENDED NEXT STEP

Material:
---
{content}
---
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--input-file")
    parser.add_argument("--text")
    parser.add_argument("--audit-type", default="engineering_quality_audit")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--out-dir",
        default="aims_workspace/bedrock_auditor/reviews",
    )
    args = parser.parse_args()

    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("bedrock_audit_%Y%m%dT%H%M%SZ")
    content = read_input(args)
    loaded_env = load_export_env(Path(args.env_file).expanduser())

    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION",
        "AIMS_BEDROCK_AUDITOR_MODEL",
    ]
    missing = [k for k in required if not loaded_env.get(k)]
    if missing:
        print(json.dumps({"status": "FAIL", "error": "missing_env", "missing": missing}, indent=2), file=sys.stderr)
        return 2

    region = loaded_env["AWS_DEFAULT_REGION"]
    model_id = loaded_env["AIMS_BEDROCK_AUDITOR_MODEL"]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": SYSTEM_INSTRUCTIONS + "\n\n" + build_prompt(content, run_id, args.audit_type)
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

    run_env = os.environ.copy()
    run_env.update(loaded_env)

    started = dt.datetime.now(dt.timezone.utc).isoformat()

    proc = subprocess.run(
        cmd,
        env=run_env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )

    evidence: Dict[str, Any] = {
        "run_id": run_id,
        "status": "UNKNOWN",
        "audit_type": args.audit_type,
        "started_utc": started,
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "region": region,
        "model_id": model_id,
        "input_chars": len(content),
        "returncode": proc.returncode,
    }

    if proc.stderr.strip():
        evidence["stderr"] = proc.stderr.strip()

    if proc.returncode != 0:
        evidence["status"] = "FAIL"
        evidence["error"] = "aws_cli_failed"
        evidence["stdout"] = proc.stdout.strip()
        return write_evidence(evidence, args.out_dir, exit_code=proc.returncode or 1)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        evidence["status"] = "FAIL"
        evidence["error"] = "invalid_json_from_aws_cli"
        evidence["stdout"] = proc.stdout.strip()
        return write_evidence(evidence, args.out_dir, exit_code=3)

    content_parts = payload.get("output", {}).get("message", {}).get("content", [])
    report_text = "\n".join(
        part.get("text", "") for part in content_parts if isinstance(part, dict)
    ).strip()

    verdict = "WARN"
    upper = report_text.upper()
    if "VERDICT: PASS" in upper:
        verdict = "PASS"
    elif "VERDICT: FAIL" in upper:
        verdict = "FAIL"

    evidence.update({
        "status": "PASS" if report_text else "FAIL",
        "auditor_verdict": verdict,
        "report_text": report_text,
        "usage": payload.get("usage", {}),
        "metrics": payload.get("metrics", {}),
        "raw_response": payload,
    })

    return write_evidence(evidence, args.out_dir, exit_code=0 if report_text else 4)


def write_evidence(evidence: Dict[str, Any], out_dir: str, exit_code: int) -> int:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_path = out_path / f"{evidence.get('run_id', 'bedrock_audit')}_{stamp}.json"
    file_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "status": evidence.get("status"),
        "auditor_verdict": evidence.get("auditor_verdict"),
        "region": evidence.get("region"),
        "model_id": evidence.get("model_id"),
        "usage": evidence.get("usage"),
        "metrics": evidence.get("metrics"),
        "evidence_file": str(file_path),
        "report_text": evidence.get("report_text"),
    }, indent=2, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
