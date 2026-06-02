#!/usr/bin/env python3
"""
AIMS Bedrock Auditor real review gate.

This gate verifies that the AWS Bedrock Claude auditor can perform a real
engineering quality review and produce evidence suitable for AIMS logs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "ops" / "tools" / "aims_bedrock_auditor_review.py"


TEST_MATERIAL = """AIMS Bedrock auditor integration candidate.

Evidence available:
- IAM user aims-bedrock-auditor exists.
- Policy allows Bedrock invoke plus model/profile read only.
- Console access is disabled.
- Secret env file is outside the repository.
- Git grep found no AWS_SECRET_ACCESS_KEY inside the project.
- Smoke wrapper passed.
- Review wrapper passed but earlier output was truncated at maxTokens=1200, now increased to 2000.

Review question:
Can this be accepted as a controlled dry-run external auditor gate, not production release gate?
"""


def main() -> int:
    if not REVIEW.exists():
        print(json.dumps({
            "gate": "bedrock_auditor_review",
            "status": "FAIL",
            "reason": f"missing review wrapper: {REVIEW}",
        }, indent=2))
        return 2

    proc = subprocess.run(
        [
            sys.executable,
            str(REVIEW),
            "--audit-type",
            "bedrock_auditor_review_gate",
            "--run-id",
            "bedrock_auditor_review_gate_test",
            "--text",
            TEST_MATERIAL,
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )

    if proc.returncode != 0:
        print(json.dumps({
            "gate": "bedrock_auditor_review",
            "status": "FAIL",
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }, indent=2))
        return proc.returncode or 1

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(json.dumps({
            "gate": "bedrock_auditor_review",
            "status": "FAIL",
            "reason": "review wrapper returned non-json stdout",
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }, indent=2))
        return 3

    report = payload.get("report_text") or ""
    auditor_verdict = payload.get("auditor_verdict")

    status = "PASS" if report and auditor_verdict in {"PASS", "WARN"} else "FAIL"

    print(json.dumps({
        "gate": "bedrock_auditor_review",
        "status": status,
        "auditor_verdict": auditor_verdict,
        "model_id": payload.get("model_id"),
        "region": payload.get("region"),
        "usage": payload.get("usage"),
        "metrics": payload.get("metrics"),
        "evidence_file": payload.get("evidence_file"),
        "report_preview": report[:1200],
    }, indent=2, ensure_ascii=False))

    return 0 if status == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
