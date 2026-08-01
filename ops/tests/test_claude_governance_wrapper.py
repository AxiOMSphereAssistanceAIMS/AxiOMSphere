from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_claude_wrapper_denies_governed_main_without_lease() -> None:
    env = dict(os.environ)
    env["AIMS_REQUIRE_GOVERNED_MUTATION"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops/scripts/claude_logi_session_wrapper.py"),
            "--launcher-path",
            "test",
            "--workspace",
            str(ROOT),
            "--claude-bin",
            "/bin/true",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 78
    assert "DIRECT_MAIN_BRANCH_DENIED" in result.stderr
