from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "ops" / "scripts" / "run_docsreg_in_compose.sh"
DEPRECATED = ROOT / "ops" / "scripts" / "run_docsreg_markitdown.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_compose_launcher_shell_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(LAUNCHER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_compose_launcher_injects_redis_urls_and_uses_aims_worker() -> None:
    text = _read(LAUNCHER)
    assert 'DOCSREG_COMPOSE_SERVICE:-aims-worker' in text
    assert 'docker compose run --rm -T' in text
    assert 'AIMS_REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'DOCSREG_REDIS_URL="redis://aims-redis:6379/0"' in text
    assert 'DOCSREG_RUNTIME_MODE="compose_network"' in text
    assert 'DOCSREG_EXTRACTOR_BACKEND="markitdown"' in text


def test_compose_launcher_fails_clearly_when_service_missing() -> None:
    text = _read(LAUNCHER)
    assert "DOCSREG_COMPOSE_SERVICE_NOT_FOUND" in text
    assert "Available services:" in text
    assert "docker compose config --services" in text


def test_deprecated_wrapper_delegates_to_compose_launcher() -> None:
    text = _read(DEPRECATED)
    assert "DEPRECATED: use ops/scripts/run_docsreg_in_compose.sh" in text
    assert 'exec "$script_dir/run_docsreg_in_compose.sh" "$@"' in text
