from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(args: list[str], *, repo_root: str | Path = ".", timeout: int = 20) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return f"[git unavailable: {exc}]"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"[git {' '.join(args)} failed] {err or out}".strip()
    return out


def changed_files_from_status(status: str) -> list[str]:
    files: list[str] = []
    for line in (status or "").splitlines():
        if not line.strip() or line.startswith("##"):
            continue
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append(path)
    return sorted(set(files))


def capture_git_snapshot(
    *,
    output_dir: str | Path,
    repo_root: str | Path = ".",
    prefix: str = "git",
) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    status = run_git(["status", "--short"], repo_root=repo_root)
    diff = run_git(["diff"], repo_root=repo_root, timeout=60)
    status_path = target / f"{prefix}_status_short.txt"
    diff_path = target / f"{prefix}_diff.patch"
    status_path.write_text(status + ("\n" if status else ""), encoding="utf-8")
    diff_path.write_text(diff + ("\n" if diff else ""), encoding="utf-8")
    return {
        "status_path": str(status_path),
        "diff_path": str(diff_path),
        "files_changed": changed_files_from_status(status),
    }


def capture_commit_diff(
    *,
    commit: str,
    output_path: str | Path,
    repo_root: str | Path = ".",
) -> str | None:
    if not commit:
        return None
    diff = run_git(["show", "--format=fuller", "--stat", "--patch", commit], repo_root=repo_root, timeout=60)
    if diff.startswith("[git "):
        return None
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(diff + ("\n" if diff else ""), encoding="utf-8")
    return str(target)
