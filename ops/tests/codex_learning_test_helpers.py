from __future__ import annotations

import json
from pathlib import Path

from ops.logi.codex_learning_traceability import REQUIRED_FILES


def write_codex_package(
    workspace: Path,
    session_id: str = "logi_codex_fixture",
    *,
    complete: bool = True,
    schema_valid: bool = True,
    legacy_schema: bool = False,
    status: str = "COMPLETED",
) -> Path:
    session_dir = workspace / "aims_workspace/logi/raw_material/codex_sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "logi_session_id": session_id,
        "aims_session_id": session_id,
        "agent": "codex",
        "source": "codex",
        "started_at": "2026-07-09T00:00:00+00:00",
        "started_at_utc": "2026-07-09T00:00:00+00:00",
        "ended_at": "2026-07-09T00:00:10+00:00" if status != "RUNNING" else None,
        "ended_at_utc": "2026-07-09T00:00:10+00:00" if status != "RUNNING" else None,
        "operator": "test",
        "workspace_root": str(workspace),
        "workspace": str(workspace),
        "command": "codex exec test",
        "codex_binary": "/tmp/codex-vendor",
        "codex_bin": "/tmp/codex-vendor",
        "wrapper_path": "/tmp/codex",
        "launcher_path": "/tmp/codex",
        "resume_of": None,
        "codex_resume_id": None,
        "codex_mode": "task",
        "task_title": "test task",
        "task_prompt_path": None,
        "exit_code": 0 if status != "RUNNING" else None,
        "status": status,
        "pid_launcher": 1,
        "pid_child": 2,
        "learning_material_status": "HANDOFF_WRITTEN" if status != "RUNNING" else "CAPTURE_STARTED",
        "traini_raw_material_status": "RAW_POINTER_ONLY",
        "artifacts": {
            "stdout_log": "stdout.log",
            "stderr_log": "stderr.log",
            "transcript": "transcript.md",
            "touched_files": "touched_files.txt",
            "evidence_links": "evidence_links.json",
            "learning_material_handoff": "learning_material_handoff.json",
        },
        "safety": {
            "raw_material_only": True,
            "not_training_data": True,
            "requires_classification": True,
            "requires_contamination_filter": True,
            "requires_slot_routing": True,
            "direct_training_allowed": False,
            "downstream_training_allowed": False,
        },
    }
    if legacy_schema:
        manifest.pop("schema_version")
        manifest.pop("safety")
        manifest.pop("artifacts")
    elif not schema_valid:
        manifest.pop("schema_version")
        manifest["safety"]["direct_training_allowed"] = True
    (session_dir / "session_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    payloads = {
        "command.txt": "codex exec test\n",
        "environment_summary.txt": "LOGI_SESSION_ID=test\n",
        "git_status_before.txt": " M before.py\n",
        "git_status_after.txt": " M after.py\n",
        "stdout.log": "stdout\n",
        "stderr.log": "",
        "transcript.md": "Codex transcript with fix and tests.\n",
        "touched_files.txt": "ops/logi/codex_learning_traceability.py\n",
        "evidence_links.json": json.dumps({"session_dir": str(session_dir)}),
        "learning_material_handoff.json": json.dumps({"not_approved_training_pairs": True, "requires_slot_router": True}),
        "final_status.json": json.dumps({"status": status, "exit_code": 0 if status != "RUNNING" else None}),
    }
    if complete:
        for name, text in payloads.items():
            (session_dir / name).write_text(text, encoding="utf-8")
    else:
        for name in ("command.txt", "environment_summary.txt", "git_status_before.txt", "transcript.md"):
            (session_dir / name).write_text(payloads[name], encoding="utf-8")
    assert (session_dir / "session_manifest.json").exists()
    if complete:
        assert all((session_dir / name).exists() for name in REQUIRED_FILES)
    return session_dir
