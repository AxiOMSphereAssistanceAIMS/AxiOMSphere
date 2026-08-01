from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_repairman_launcher_denies_before_child_when_governance_required() -> None:
    env = dict(os.environ)
    env["AIMS_REQUIRE_GOVERNED_MUTATION"] = "1"
    result = subprocess.run(["bash", str(ROOT / "ops/scripts/Repairman_Audit_Autonomy_start.sh")], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 78
