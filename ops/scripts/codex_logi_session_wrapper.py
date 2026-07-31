#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DEFAULT = Path("/home/axi_omi_sphere/aims-workspace")
# No default runtime limit: a wrapped Codex session runs until it exits on
# its own. Long-running supervised work (audits, multi-file remediation)
# must not be killed mid-task by an arbitrary wall-clock cutoff. Set
# AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS to a positive integer to opt into a
# limit for a specific invocation.
DEFAULT_MAX_RUNTIME_SECONDS: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_text(cmd: list[str], cwd: Path) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=20).stdout
    except Exception as exc:
        return f"UNAVAILABLE: {exc}\n"


def _detect_mode(args: list[str]) -> tuple[str, str | None]:
    lowered = [arg.lower() for arg in args]
    for key in ("resume", "continue"):
        if key in lowered:
            idx = lowered.index(key)
            resume_id = args[idx + 1] if idx + 1 < len(args) and not args[idx + 1].startswith("-") else None
            return ("resume" if key == "resume" else "continue", resume_id)
    if "exec" in lowered:
        return "task", None
    return "new", None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _build_paths(workspace: Path, session_id: str) -> dict[str, Path]:
    session_dir = workspace / "aims_workspace/logi/raw_material/codex_sessions" / session_id
    return {
        "session_dir": session_dir,
        "manifest": session_dir / "session_manifest.json",
        "command": session_dir / "command.txt",
        "environment": session_dir / "environment_summary.txt",
        "git_before": session_dir / "git_status_before.txt",
        "git_after": session_dir / "git_status_after.txt",
        "stdout": session_dir / "stdout.log",
        "stderr": session_dir / "stderr.log",
        "transcript": session_dir / "transcript.md",
        "touched": session_dir / "touched_files.txt",
        "evidence": session_dir / "evidence_links.json",
        "handoff": session_dir / "learning_material_handoff.json",
        "final": session_dir / "final_status.json",
        "index": workspace / "aims_workspace/logi/raw_material/codex_sessions/index.jsonl",
        "traini_pointer": workspace / "aims_workspace/traini/raw_material/inbox/codex_sessions" / f"{session_id}.json",
    }


def _launch_unregistered(codex_bin: str, child_args: list[str]) -> int:
    os.environ["CODEX_LOGI_SESSION_NONCOMPLIANT"] = "1"
    return subprocess.call([codex_bin, *child_args])


def _max_runtime_seconds() -> int | None:
    """None means unbounded — subprocess.communicate/wait(timeout=None) blocks
    indefinitely, which is the desired default. Only an explicit positive
    AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS opts a session into a limit; unset,
    empty, non-numeric, zero, or negative all mean "no limit", not "use the
    old 3600s default" — there is no implicit limit anymore.
    """
    raw = os.environ.get("AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS")
    if not raw:
        return DEFAULT_MAX_RUNTIME_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_RUNTIME_SECONDS
    return value if value > 0 else None


def _terminate_group(proc: subprocess.Popen[object]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_wrapped(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    codex_bin = str(Path(args.codex_bin).expanduser())
    child_args = list(args.child_args or [])
    if child_args and child_args[0] == "--":
        child_args = child_args[1:]
    started = _now()
    session_id = os.environ.get("LOGI_SESSION_ID") or f"logi_codex_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    aims_session_id = os.environ.get("AIMS_SESSION_ID") or session_id
    mode, resume_id = _detect_mode(child_args)
    paths = _build_paths(workspace, session_id)
    session_dir = paths["session_dir"]

    try:
        active_dir = os.environ.get("CODEX_LOGI_SESSION_DIR")
        if (
            os.environ.get("AIMS_CODEX_WRAPPER_ACTIVE") == "1"
            and (
                not os.environ.get("CODEX_LOGI_WRAPPER_CHILD_PROBE")
                or (active_dir and Path(active_dir).resolve() == session_dir.resolve())
            )
        ):
            raise RuntimeError("AIMS_CODEX_WRAPPER_ACTIVE recursion guard triggered")
        is_installed_vendor = "/codex-linux-arm64/vendor/" in str(Path(codex_bin).resolve())
        if Path(codex_bin).name == "codex" and not is_installed_vendor and "codex-vendor" not in str(codex_bin):
            bypass_report = {
                "detected_at_utc": started,
                "status": "DIRECT_VENDOR_BYPASS_RISK",
                "codex_bin": codex_bin,
                "reason": "wrapper child binary should be the installed Codex CLI/vendor binary, not the AIMS wrapper path",
            }
            _write_json(workspace / "aims_workspace/logi/raw_material/codex_sessions/bypass_detection_report.json", bypass_report)
        session_dir.mkdir(parents=True, exist_ok=False)
        command = [codex_bin, *child_args]
        if os.environ.get("CODEX_LOGI_WRAPPER_CHILD_PROBE") == "1":
            command = [
                "bash",
                "-lc",
                "env | sort | grep -E '^(LOGI|AIMS|CODEX)_' && echo CODEX_LOGI_WRAPPER_CHILD_PROBE_OK",
            ]
        env = os.environ.copy()
        env.update(
            {
                "LOGI_SESSION_ID": session_id,
                "AIMS_SESSION_ID": aims_session_id,
                "AIMS_AGENT": "codex",
                "CODEX_LAUNCHER_WRAPPED": "1",
                "CODEX_RESUME_ID": resume_id or "",
                "CODEX_LOGI_SESSION_DIR": str(session_dir),
                "CODEX_LOGI_LEARNING_CAPTURE": "1",
                "AIMS_CODEX_WRAPPER_ACTIVE": "1",
                "CODEX_VENDOR_BINARY": codex_bin,
            }
        )
        artifacts = {
            "stdout_log": "stdout.log",
            "stderr_log": "stderr.log",
            "transcript": "transcript.md",
            "touched_files": "touched_files.txt",
            "evidence_links": "evidence_links.json",
            "learning_material_handoff": "learning_material_handoff.json",
        }
        safety = {
            "raw_material_only": True,
            "not_training_data": True,
            "requires_classification": True,
            "requires_contamination_filter": True,
            "requires_slot_routing": True,
            "direct_training_allowed": False,
            "downstream_training_allowed": False,
        }
        manifest = {
            "schema_version": "1.0",
            "logi_session_id": session_id,
            "aims_session_id": aims_session_id,
            "agent": "codex",
            "source": "codex",
            "launcher_path": args.launcher_path,
            "wrapper_path": args.launcher_path,
            "codex_bin": codex_bin,
            "codex_binary": codex_bin,
            "codex_mode": mode,
            "codex_resume_id": resume_id,
            "resume_of": resume_id,
            "workspace": str(workspace),
            "workspace_root": str(workspace),
            "started_at_utc": started,
            "started_at": started,
            "ended_at_utc": None,
            "ended_at": None,
            "operator": os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown",
            "command": shlex.join(command),
            "task_title": " ".join(child_args[:6]) if child_args else "codex interactive session",
            "task_prompt_path": None,
            "exit_code": None,
            "status": "RUNNING",
            "max_runtime_seconds": _max_runtime_seconds(),
            "pid_launcher": os.getpid(),
            "pid_child": 0,
            "learning_material_status": "CAPTURE_STARTED",
            "traini_raw_material_status": "RAW_POINTER_ONLY",
            "artifacts": artifacts,
            "safety": safety,
        }
        _write_json(paths["manifest"], manifest)
        paths["command"].write_text(shlex.join(command) + "\n", encoding="utf-8")
        paths["environment"].write_text(
            "\n".join(
                f"{key}={env.get(key, '')}"
                for key in (
                    "LOGI_SESSION_ID",
                    "AIMS_SESSION_ID",
                    "AIMS_AGENT",
                    "CODEX_LAUNCHER_WRAPPED",
                    "CODEX_RESUME_ID",
                    "CODEX_LOGI_SESSION_DIR",
                    "CODEX_LOGI_LEARNING_CAPTURE",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        paths["git_before"].write_text(_run_text(["git", "status", "--short"], workspace), encoding="utf-8")
    except Exception as exc:
        if os.environ.get("CODEX_ALLOW_UNREGISTERED_SESSION") == "1":
            print(f"WARNING: Logi session capture failed, launching unregistered: {exc}", file=sys.stderr)
            return _launch_unregistered(codex_bin, child_args)
        print(f"ERROR: cannot create Logi Codex session capture: {exc}", file=sys.stderr)
        return 126

    exit_code = 1
    child_pid = 0
    try:
        if os.environ.get("CODEX_LOGI_WRAPPER_CHILD_PROBE") == "1":
            proc = subprocess.Popen(command, cwd=workspace, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            child_pid = proc.pid
            try:
                stdout, stderr = proc.communicate(timeout=_max_runtime_seconds())
            except subprocess.TimeoutExpired:
                _terminate_group(proc)
                stdout, stderr = "", f"Codex session exceeded AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS={_max_runtime_seconds()}\n"
                exit_code = 124
            else:
                exit_code = proc.returncode
            paths["stdout"].write_text(stdout or "", encoding="utf-8")
            paths["stderr"].write_text(stderr or "", encoding="utf-8")
            paths["transcript"].write_text((stdout or "") + ("\n--- STDERR ---\n" + stderr if stderr else ""), encoding="utf-8")
            print(stdout or "", end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
            if exit_code != 124:
                exit_code = proc.returncode
        elif shutil.which("script"):
            transcript = paths["transcript"]
            command_string = shlex.join(command)
            proc = subprocess.Popen(["script", "-q", "-e", "-a", str(transcript), "-c", command_string], cwd=workspace, env=env, start_new_session=True)
            child_pid = proc.pid
            try:
                exit_code = proc.wait(timeout=_max_runtime_seconds())
            except subprocess.TimeoutExpired:
                _terminate_group(proc)
                exit_code = 124
                paths["stderr"].write_text(
                    f"Codex session exceeded AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS={_max_runtime_seconds()}\n",
                    encoding="utf-8",
                )
            paths["stdout"].write_text("Interactive transcript captured in transcript.md via script(1).\n", encoding="utf-8")
            if not paths["stderr"].exists():
                paths["stderr"].write_text("Interactive stderr is included in transcript.md via script(1).\n", encoding="utf-8")
        else:
            proc = subprocess.Popen(command, cwd=workspace, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            child_pid = proc.pid
            try:
                stdout, stderr = proc.communicate(timeout=_max_runtime_seconds())
            except subprocess.TimeoutExpired:
                _terminate_group(proc)
                stdout, stderr = "", f"Codex session exceeded AIMS_CODEX_SESSION_MAX_RUNTIME_SECONDS={_max_runtime_seconds()}\n"
                exit_code = 124
            else:
                exit_code = proc.returncode
            paths["stdout"].write_text(stdout or "", encoding="utf-8")
            paths["stderr"].write_text(stderr or "", encoding="utf-8")
            paths["transcript"].write_text((stdout or "") + ("\n--- STDERR ---\n" + stderr if stderr else ""), encoding="utf-8")
            print(stdout or "", end="")
            if stderr:
                print(stderr, end="", file=sys.stderr)
    finally:
        ended = _now()
        status = "COMPLETED" if exit_code == 0 else "FAILED"
        git_after = _run_text(["git", "status", "--short"], workspace)
        paths["git_after"].write_text(git_after, encoding="utf-8")
        paths["touched"].write_text(git_after, encoding="utf-8")
        evidence_links = {
            "session_dir": str(paths["session_dir"]),
            "manifest_path": str(paths["manifest"]),
            "transcript_path": str(paths["transcript"]),
            "stdout_path": str(paths["stdout"]),
            "stderr_path": str(paths["stderr"]),
        }
        _write_json(paths["evidence"], evidence_links)
        transcript_sha256 = _sha256(paths["transcript"]) if paths["transcript"].is_file() else None
        transcript_size_bytes = paths["transcript"].stat().st_size if paths["transcript"].is_file() else 0
        handoff = {
            "material_id": f"codex_session_{session_id}",
            "material_type": "codex_session_transcript",
            "source_agent": "codex",
            "target_consumer": ["logi", "traini_raw_material_review"],
            "not_approved_training_pairs": True,
            "requires_classification": True,
            "requires_contamination_filter": True,
            "requires_slot_router": True,
            "requires_pair_conversion": True,
            "session_dir": str(paths["session_dir"]),
            "transcript_path": str(paths["transcript"]),
            "transcript_sha256": transcript_sha256,
            "transcript_size_bytes": transcript_size_bytes,
            "manifest_path": str(paths["manifest"]),
            "summary": f"Codex launcher session {session_id} captured for Logi learning material.",
            "created_at_utc": ended,
        }
        _write_json(paths["handoff"], handoff)
        traini_pointer_status = "WRITTEN"
        traini_pointer_error = None
        try:
            _write_json(paths["traini_pointer"], {**handoff, "target_consumer": ["traini_raw_material_review"], "raw_only": True})
        except Exception as exc:
            traini_pointer_status = "FAILED_OPTIONAL"
            traini_pointer_error = str(exc)
        final = {
            "logi_session_id": session_id,
            "aims_session_id": aims_session_id,
            "status": status,
            "exit_code": exit_code,
            "started_at_utc": started,
            "ended_at_utc": ended,
            "terminal_time_source": "wrapper_final_status",
            "transcript_sha256": transcript_sha256,
            "transcript_size_bytes": transcript_size_bytes,
            "pid_launcher": os.getpid(),
            "pid_child": child_pid,
            "learning_material_handoff": str(paths["handoff"]),
            "traini_raw_material_pointer_status": traini_pointer_status,
            "traini_raw_material_pointer_error": traini_pointer_error,
        }
        _write_json(paths["final"], final)
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        manifest.update(
            {
                "ended_at_utc": ended,
                "ended_at": ended,
                "status": status,
                "exit_code": exit_code,
                "pid_child": child_pid,
                "learning_material_status": "HANDOFF_WRITTEN",
                "traini_raw_material_status": "RAW_POINTER_ONLY" if traini_pointer_status == "WRITTEN" else "RAW_POINTER_OPTIONAL_FAILED",
                "traini_raw_material_pointer_error": traini_pointer_error,
                "final_status_path": str(paths["final"]),
                "transcript_sha256": transcript_sha256,
                "transcript_size_bytes": transcript_size_bytes,
                "terminal_time_source": "wrapper_final_status",
            }
        )
        _write_json(paths["manifest"], manifest)
        _append_jsonl(
            paths["index"],
            {
                "logi_session_id": session_id,
                "aims_session_id": aims_session_id,
                "agent": "codex",
                "status": status,
                "started_at_utc": started,
                "ended_at_utc": ended,
                "session_dir": str(paths["session_dir"]),
                "handoff_path": str(paths["handoff"]),
                "not_approved_training_pairs": True,
            },
        )
    return int(exit_code)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Codex launcher sessions as Logi learning raw material.")
    parser.add_argument("--launcher-path", required=True)
    parser.add_argument("--workspace", default=str(ROOT_DEFAULT))
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return run_wrapped(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
