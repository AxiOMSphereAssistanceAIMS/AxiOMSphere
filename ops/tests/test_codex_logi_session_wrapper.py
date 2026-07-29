from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run_probe(session_id: str, tmp_workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_LOGI_WRAPPER_CHILD_PROBE"] = "1"
    env["LOGI_SESSION_ID"] = session_id
    return subprocess.run(
        [
            "python3",
            str(ROOT / "ops/scripts/codex_logi_session_wrapper.py"),
            "--launcher-path",
            "/tmp/codex-aims-test",
            "--workspace",
            str(tmp_workspace),
            "--codex-bin",
            "/bin/echo",
            "--",
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_wrapper_probe_writes_manifest_handoff_index_final_and_env(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "logi_codex_unit_probe"

    proc = _run_probe(session_id, workspace, "exec", "unit task")

    assert proc.returncode == 0
    assert "LOGI_SESSION_ID=logi_codex_unit_probe" in proc.stdout
    assert "CODEX_LOGI_LEARNING_CAPTURE=1" in proc.stdout
    session_dir = workspace / "aims_workspace/logi/raw_material/codex_sessions" / session_id
    manifest = json.loads((session_dir / "session_manifest.json").read_text(encoding="utf-8"))
    handoff = json.loads((session_dir / "learning_material_handoff.json").read_text(encoding="utf-8"))
    final = json.loads((session_dir / "final_status.json").read_text(encoding="utf-8"))
    index = (workspace / "aims_workspace/logi/raw_material/codex_sessions/index.jsonl").read_text(encoding="utf-8")
    pointer = workspace / "aims_workspace/traini/raw_material/inbox/codex_sessions" / f"{session_id}.json"

    assert manifest["logi_session_id"] == session_id
    assert manifest["codex_mode"] == "task"
    assert manifest["status"] == "COMPLETED"
    assert manifest["schema_version"] == "1.0"
    assert manifest["source"] == "codex"
    assert manifest["codex_binary"] == "/bin/echo"
    assert manifest["wrapper_path"] == "/tmp/codex-aims-test"
    assert manifest["artifacts"]["transcript"] == "transcript.md"
    assert manifest["safety"]["raw_material_only"] is True
    assert manifest["safety"]["direct_training_allowed"] is False
    assert manifest["safety"]["downstream_training_allowed"] is False
    assert handoff["not_approved_training_pairs"] is True
    assert handoff["requires_slot_router"] is True
    assert final["exit_code"] == 0
    assert session_id in index
    assert pointer.exists()


def test_wrapper_captures_resume_id(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "logi_codex_unit_resume"

    proc = _run_probe(session_id, workspace, "resume", "codex_resume_123")

    assert proc.returncode == 0
    manifest = json.loads(
        (workspace / "aims_workspace/logi/raw_material/codex_sessions" / session_id / "session_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["codex_mode"] == "resume"
    assert manifest["codex_resume_id"] == "codex_resume_123"
    assert manifest["resume_of"] == "codex_resume_123"


def test_codex_resolves_to_aims_wrapper() -> None:
    proc = subprocess.run(["which", "codex"], text=True, capture_output=True, check=True)
    assert proc.stdout.strip() == "/home/axi_omi_sphere/.local/bin/codex"


def test_command_v_codex_resolves_to_aims_wrapper() -> None:
    proc = subprocess.run(["bash", "-lc", "command -v codex"], text=True, capture_output=True, check=True)
    assert proc.stdout.strip() == "/home/axi_omi_sphere/.local/bin/codex"


def test_type_codex_resolves_to_aims_wrapper() -> None:
    proc = subprocess.run(["bash", "-lc", "type codex"], text=True, capture_output=True, check=True)
    assert "codex is /home/axi_omi_sphere/.local/bin/codex" in proc.stdout


def test_codex_vendor_binary_preserved() -> None:
    proc = subprocess.run(["bash", "-lc", "command -v codex-vendor && codex-vendor --version"], text=True, capture_output=True, check=True)
    assert "/codex-vendor" in proc.stdout
    assert "codex-cli" in proc.stdout


def test_direct_vendor_bypass_detected_or_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake = tmp_path / "codex"
    fake.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    env = os.environ.copy()
    env["CODEX_LOGI_WRAPPER_CHILD_PROBE"] = "1"
    env["LOGI_SESSION_ID"] = "logi_codex_bypass_probe"
    proc = subprocess.run(
        [
            "python3",
            str(ROOT / "ops/scripts/codex_logi_session_wrapper.py"),
            "--launcher-path",
            "/tmp/codex-aims-test",
            "--workspace",
            str(workspace),
            "--codex-bin",
            str(fake),
            "--",
            "exec",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert (workspace / "aims_workspace/logi/raw_material/codex_sessions/bypass_detection_report.json").exists()


def test_wrapper_recursion_guard(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = os.environ.copy()
    env["AIMS_CODEX_WRAPPER_ACTIVE"] = "1"
    env["LOGI_SESSION_ID"] = "logi_codex_recursion"
    proc = subprocess.run(
        [
            "python3",
            str(ROOT / "ops/scripts/codex_logi_session_wrapper.py"),
            "--launcher-path",
            "/tmp/codex-aims-test",
            "--workspace",
            str(workspace),
            "--codex-bin",
            "/bin/echo",
            "--",
            "exec",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 126
    assert "recursion guard" in proc.stderr


def test_wrapper_fails_closed_when_session_dir_cannot_be_created(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    blocked = workspace / "aims_workspace/logi/raw_material/codex_sessions"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("not a directory", encoding="utf-8")
    env = os.environ.copy()
    env["CODEX_LOGI_WRAPPER_CHILD_PROBE"] = "1"
    env["LOGI_SESSION_ID"] = "logi_codex_blocked"

    proc = subprocess.run(
        [
            "python3",
            str(ROOT / "ops/scripts/codex_logi_session_wrapper.py"),
            "--launcher-path",
            "/tmp/codex-aims-test",
            "--workspace",
            str(workspace),
            "--codex-bin",
            "/bin/echo",
            "--",
            "exec",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 126
    assert "cannot create Logi Codex session capture" in proc.stderr


def _run_wrapped(session_id: str, tmp_workspace: Path, codex_bin: str, child_args: list[str],
                  *, max_runtime_env: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CODEX_LOGI_WRAPPER_CHILD_PROBE", None)
    env["LOGI_SESSION_ID"] = session_id
    if max_runtime_env is None:
        env.pop("AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS", None)
    else:
        env["AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS"] = max_runtime_env
    return subprocess.run(
        [
            "python3",
            str(ROOT / "ops/scripts/codex_logi_session_wrapper.py"),
            "--launcher-path", "/tmp/codex-aims-test",
            "--workspace", str(tmp_workspace),
            "--codex-bin", codex_bin,
            "--", *child_args,
        ],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
    )


def _manifest_for(tmp_workspace: Path, session_id: str) -> dict:
    session_dir = tmp_workspace / "aims_workspace/logi/raw_material/codex_sessions" / session_id
    return json.loads((session_dir / "session_manifest.json").read_text(encoding="utf-8"))


def test_no_runtime_limit_by_default(tmp_path: Path) -> None:
    """The historical 3600s default silently killed sessions no one asked to
    limit. Unset AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS must mean unbounded,
    not '3600s unless overridden'."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "logi_codex_no_limit"

    proc = _run_wrapped(session_id, workspace, "/bin/sleep", ["1"])

    assert proc.returncode == 0
    manifest = _manifest_for(workspace, session_id)
    assert manifest["max_runtime_seconds"] is None
    assert manifest["status"] == "COMPLETED"
    assert manifest["exit_code"] == 0


def test_explicit_positive_limit_still_enforced(tmp_path: Path) -> None:
    """Opting into a limit must still work: this is a configurable safety
    net, not something removed entirely — only the *implicit* default is
    gone."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "logi_codex_explicit_limit"

    proc = _run_wrapped(session_id, workspace, "/bin/sleep", ["5"], max_runtime_env="1")

    manifest = _manifest_for(workspace, session_id)
    assert manifest["max_runtime_seconds"] == 1
    assert manifest["status"] == "FAILED"
    assert manifest["exit_code"] == 124


def test_zero_and_negative_limit_mean_no_limit_not_the_old_default(tmp_path: Path) -> None:
    for value, session_id in (("0", "logi_codex_zero_limit"), ("-5", "logi_codex_negative_limit")):
        workspace = tmp_path / f"ws_{session_id}"
        workspace.mkdir()
        proc = _run_wrapped(session_id, workspace, "/bin/sleep", ["1"], max_runtime_env=value)
        assert proc.returncode == 0
        manifest = _manifest_for(workspace, session_id)
        assert manifest["max_runtime_seconds"] is None
