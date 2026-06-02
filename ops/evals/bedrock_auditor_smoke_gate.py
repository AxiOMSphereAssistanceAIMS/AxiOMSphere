#!/usr/bin/env python3
"""
AIMS Bedrock Auditor dry-run gate.

This gate verifies that the external AWS Bedrock Claude auditor path is usable
from the local AIMS runtime. It does not expose secrets and delegates the actual
model call to ops/tools/aims_bedrock_auditor_smoke.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "ops" / "tools" / "aims_bedrock_auditor_smoke.py"


def main() -> int:
    if not SMOKE.exists():
        print(json.dumps({
            "gate": "bedrock_auditor_smoke",
            "status": "FAIL",
            "reason": f"missing smoke wrapper: {SMOKE}",
        }, indent=2))
        return 2

    proc = subprocess.run(
        [sys.executable, str(SMOKE)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )

    if proc.returncode != 0:
        print(json.dumps({
            "gate": "bedrock_auditor_smoke",
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
            "gate": "bedrock_auditor_smoke",
            "status": "FAIL",
            "reason": "smoke wrapper returned non-json stdout",
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }, indent=2))
        return 3

    gate_status = "PASS" if payload.get("status") == "PASS" else "WARN"

    print(json.dumps({
        "gate": "bedrock_auditor_smoke",
        "status": gate_status,
        "model_id": payload.get("model_id"),
        "region": payload.get("region"),
        "usage": payload.get("usage"),
        "metrics": payload.get("metrics"),
        "evidence_file": payload.get("evidence_file"),
    }, indent=2))

    return 0 if gate_status == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
