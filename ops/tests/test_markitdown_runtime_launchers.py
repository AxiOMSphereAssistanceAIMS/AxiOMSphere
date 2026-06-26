from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "ops" / "scripts" / "markitdown_runtime.sh"
DOCSREG = ROOT / "ops" / "scripts" / "run_docsreg_markitdown.sh"
DOCSREG_COMPOSE = ROOT / "ops" / "scripts" / "run_docsreg_in_compose.sh"
DOCGEN = ROOT / "ops" / "scripts" / "run_docgen_markitdown_quality_loop.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_markitdown_runtime_shell_syntax() -> None:
    for script in (RUNTIME, DOCSREG, DOCGEN):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_markitdown_runtime_default_python_points_to_repo_venv() -> None:
    result = subprocess.run(
        ["bash", str(RUNTIME), "--print-python"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("/.venv-markitdown/bin/python")


def test_markitdown_runtime_env_override_is_supported(tmp_path: Path) -> None:
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    command = (
        "source ops/scripts/markitdown_runtime.sh; "
        "AIMS_MARKITDOWN_PYTHON='%s'; "
        "aims_markitdown_python '%s'"
    ) % (fake_python, ROOT)
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(fake_python)


def test_docsreg_compose_launcher_forces_compose_runtime_and_redis_url() -> None:
    text = _read(DOCSREG_COMPOSE)

    assert 'DOCSREG_COMPOSE_SERVICE:-aims-worker' in text
    assert 'docker compose run --rm -T' in text
    assert 'AIMS_REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'DOCSREG_REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'DOCSREG_EXTRACTOR_BACKEND="markitdown"' in text
    assert 'DOCSREG_RUNTIME_MODE="compose_network"' in text


def test_deprecated_docsreg_wrapper_delegates_to_compose_launcher() -> None:
    text = _read(DOCSREG)

    assert "DEPRECATED: use ops/scripts/run_docsreg_in_compose.sh" in text
    assert 'exec "$script_dir/run_docsreg_in_compose.sh" "$@"' in text


def test_docgen_launcher_forces_markitdown_normalization_and_venv_python() -> None:
    text = _read(DOCGEN)

    assert 'source "$script_dir/markitdown_runtime.sh"' in text
    assert 'export DOCGEN_MARKITDOWN_NORMALIZATION="1"' in text
    assert (
        'exec "$AIMS_MARKITDOWN_PYTHON" -m '
        'ops.docgen.self_improvement.run_quality_loop "$@"'
    ) in text
