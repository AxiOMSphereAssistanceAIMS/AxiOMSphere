#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import shlex
import socket
import subprocess
import sys
import uuid

SECRET_MARKERS = (
    "TOKEN", "KEY", "SECRET", "PASSWORD", "COOKIE", "AUTH",
    "SESSION", "CREDENTIAL", "BEARER"
)

def redact_env(env):
    out = {}
    for k, v in sorted(env.items()):
        if any(m in k.upper() for m in SECRET_MARKERS):
            out[k] = "<REDACTED>"
        else:
            out[k] = v
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher-path", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--claude-bin", required=True)
    ap.add_argument("--session-kind", default="claude_code_subscription")
    ap.add_argument("--governance-task-id")
    ap.add_argument("--governance-branch")
    ap.add_argument("--governance-worktree")
    ap.add_argument("--governance-lease")
    ap.add_argument("--governance-owned-file", action="append")
    ap.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    workspace = pathlib.Path(args.workspace).resolve()
    if not workspace.exists():
        print(f"ERROR: workspace does not exist: {workspace}", file=sys.stderr)
        return 2
    mandatory = os.environ.get("AIMS_REQUIRE_GOVERNED_MUTATION") == "1" or pathlib.Path("/tmp/aims-governance-mandatory").exists()
    if mandatory or args.governance_task_id:
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from ops.self_learning.governed_mutation_preflight import mutation_preflight
        preflight = mutation_preflight(
            workspace,
            task_id=args.governance_task_id or "missing-task-id",
            target_branch=args.governance_branch or "main",
            worktree_path=pathlib.Path(args.governance_worktree or workspace),
            lease_path=pathlib.Path(args.governance_lease or workspace / "aims_workspace/agent_architecture_status/component_lease_registry.jsonl"),
            owned_files=list(args.governance_owned_file or []),
        )
        if not preflight["allowed"]:
            print(json.dumps({"governance_preflight": preflight}, ensure_ascii=False), file=sys.stderr)
            return 78

    raw_root = workspace / "aims_workspace" / "logi" / "raw_material" / "claude_sessions"
    raw_root.mkdir(parents=True, exist_ok=True)

    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_id = f"logi_claude_{ts}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    run_dir = raw_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    transcript = run_dir / "transcript.md"
    metadata = run_dir / "metadata.json"
    report = run_dir / "session_report.md"
    env_file = run_dir / "env_redacted.json"
    command_file = run_dir / "command.txt"
    exit_file = run_dir / "exit_status.json"

    claude_args = list(args.claude_args)
    if claude_args and claude_args[0] == "--":
        claude_args = claude_args[1:]

    cmd = [args.claude_bin] + claude_args

    env = os.environ.copy()
    env["AIMS_LOGI_SESSION_WRAPPER"] = "1"
    env["AIMS_LOGI_SESSION_KIND"] = args.session_kind
    env["AIMS_LOGI_SESSION_ID"] = run_id
    env["AIMS_LOGI_SESSION_DIR"] = str(run_dir)
    env["AIMS_LOGI_TRANSCRIPT"] = str(transcript)
    env["AIMS_WORKSPACE"] = str(workspace)

    meta = {
        "run_id": run_id,
        "session_kind": args.session_kind,
        "created_utc": ts,
        "workspace": str(workspace),
        "launcher_path": args.launcher_path,
        "claude_bin": args.claude_bin,
        "claude_args": claude_args,
        "command": cmd,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "user": env.get("USER"),
        "home": env.get("HOME"),
        "transcript": str(transcript),
        "report": str(report),
    }

    metadata.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    env_file.write_text(json.dumps(redact_env(env), indent=2, ensure_ascii=False) + "\n")
    command_file.write_text(" ".join(shlex.quote(x) for x in cmd) + "\n")

    report.write_text(
        "# Claude Code Logi Session Report\n\n"
        f"- run_id: `{run_id}`\n"
        f"- session_kind: `{args.session_kind}`\n"
        f"- created_utc: `{ts}`\n"
        f"- workspace: `{workspace}`\n"
        f"- launcher: `{args.launcher_path}`\n"
        f"- transcript: `{transcript}`\n"
        f"- status: `RUNNING`\n\n"
        "## Purpose\n\n"
        "Capture Claude Code subscription terminal session for Logi raw material, "
        "self-learning, repair analysis, and project training corpus extraction.\n\n"
        "## Completion\n\n"
        "Pending until process exits.\n",
        encoding="utf-8",
    )

    print("=== AIMS Claude Logi Session Wrapper ===")
    print(f"run_id={run_id}")
    print(f"workspace={workspace}")
    print(f"transcript={transcript}")
    print(f"report={report}")
    print("=======================================")

    script_cmd = [
        "script",
        "-q",
        "-e",
        "-a",
        str(transcript),
        "-c",
        " ".join(shlex.quote(x) for x in cmd),
    ]

    rc = 255
    try:
        rc = subprocess.call(script_cmd, cwd=str(workspace), env=env)
        return rc
    finally:
        finished = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        exit_data = {
            "run_id": run_id,
            "finished_utc": finished,
            "exit_code": rc,
            "transcript": str(transcript),
            "report": str(report),
        }
        exit_file.write_text(json.dumps(exit_data, indent=2, ensure_ascii=False) + "\n")

        report.write_text(
            "# Claude Code Logi Session Report\n\n"
            f"- run_id: `{run_id}`\n"
            f"- session_kind: `{args.session_kind}`\n"
            f"- created_utc: `{ts}`\n"
            f"- finished_utc: `{finished}`\n"
            f"- workspace: `{workspace}`\n"
            f"- launcher: `{args.launcher_path}`\n"
            f"- transcript: `{transcript}`\n"
            f"- exit_code: `{rc}`\n"
            f"- status: `COMPLETED` if exit_code is 0 else `EXITED_NONZERO`\n\n"
            "## Logi / Self-learning use\n\n"
            "- transcript.md is the raw terminal dialogue.\n"
            "- env_redacted.json is safe environment context.\n"
            "- metadata.json records launcher, command, workspace, and session identity.\n"
            "- This session can be ingested by Logi for lessons, repair pairs, action decisions, and project self-development.\n",
            encoding="utf-8",
        )

if __name__ == "__main__":
    raise SystemExit(main())
