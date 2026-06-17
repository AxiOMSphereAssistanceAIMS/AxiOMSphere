"""
DOCSREG fresh-start cycle guard — validates and creates a clean cycle directory.

Ensures each certification cycle begins from a known-clean filesystem state so
that evidence from prior runs can never contaminate the current run.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It uses only the Python standard library.

Exports
-------
CYCLE_SUBDIRS         — tuple of 6 subdirectory names required per cycle
FreshStartResult      — dataclass describing the outcome of a fresh-start check
assert_fresh_start_cycle(cycle_dir) -> FreshStartResult
    Main gate — never raises; creates missing dirs and reports dirty state.
make_cycle_dir(base_dir, cycle_number) -> Path
    Convenience constructor; returns the expected cycle Path without I/O.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("docsreg_fresh_start")

# ── Required cycle subdirectories ─────────────────────────────────────────────

CYCLE_SUBDIRS: tuple[str, ...] = (
    "fresh_input",
    "generated",
    "validation",
    "audit",
    "repair_plan",
    "evidence",
)


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class FreshStartResult:
    """Outcome of a single fresh-start cycle guard check.

    Attributes
    ----------
    passed:
        ``True`` when the cycle directory is ready for a clean run.
    cycle_dir:
        String path of the cycle directory that was checked or created.
    missing_subdirs:
        Names of subdirectories that were absent and have since been created.
    existing_files:
        Relative paths (as strings) of files found inside the cycle tree.
        Non-empty only in the dirty-state (``passed=False``) case.
    notes:
        Human-readable annotation describing the outcome.
    """

    passed: bool
    cycle_dir: str = ""
    missing_subdirs: list[str] = field(default_factory=list)
    existing_files: list[str] = field(default_factory=list)
    notes: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _create_subdirs(cycle_path: Path) -> list[str]:
    """Create all CYCLE_SUBDIRS under *cycle_path*; return names successfully created."""
    created: list[str] = []
    for name in CYCLE_SUBDIRS:
        subdir = cycle_path / name
        try:
            subdir.mkdir(parents=True, exist_ok=True)
            created.append(name)
        except (OSError, FileExistsError) as exc:
            log.warning(
                "fresh_start: could not create subdir %r: %s", str(subdir), exc
            )
    return created


def _collect_existing_files(cycle_path: Path) -> list[str]:
    """Return relative string paths of all files found anywhere under *cycle_path*."""
    found: list[str] = []
    for p in cycle_path.rglob("*"):
        if p.is_file():
            found.append(str(p.relative_to(cycle_path)))
    return found


# ── Public API ────────────────────────────────────────────────────────────────


def assert_fresh_start_cycle(cycle_dir: str | Path) -> FreshStartResult:
    """Validate or create a clean cycle directory for a fresh certification run.

    Scenarios handled — this function never raises:

    1. *cycle_dir* does not exist → create it and all 6 subdirs → PASS,
       ``notes="cycle directory created"``.
    2. *cycle_dir* exists but contains no subdirs → create all 6 → PASS,
       ``notes="subdirectories created"``.
    3. All 6 subdirs present and every subdir is empty → PASS,
       ``notes="fresh start confirmed"``.
    4. All 6 subdirs present but files exist inside the tree → FAIL,
       ``existing_files`` populated, ``notes="cycle directory is not clean"``.
    5. *cycle_dir* exists, some subdirs missing → create missing ones → PASS,
       ``missing_subdirs`` populated, ``notes="missing subdirectories created"``.
    6. Any unexpected exception → FAIL, ``notes="unexpected error: <exc>"``.

    Args:
        cycle_dir: Path to the cycle working directory.  Accepts both
            :class:`str` and :class:`pathlib.Path`.

    Returns:
        :class:`FreshStartResult` — never raises.
    """
    try:
        cycle_path = Path(cycle_dir)
        cycle_str = str(cycle_path)

        # ── Scenario 1: directory does not exist ──────────────────────────────
        if not cycle_path.exists():
            try:
                cycle_path.mkdir(parents=True, exist_ok=True)
            except (OSError, FileExistsError) as exc:
                log.error(
                    "fresh_start: could not create cycle dir %r: %s", cycle_str, exc
                )
                return FreshStartResult(
                    passed=False,
                    notes=f"unexpected error: {exc}",
                )
            _create_subdirs(cycle_path)
            log.info("fresh_start: PASS — cycle directory created: %s", cycle_str)
            return FreshStartResult(
                passed=True,
                cycle_dir=cycle_str,
                notes="cycle directory created",
            )

        # ── Directory exists — inspect its subdirs ────────────────────────────
        present_subdirs: list[str] = [
            name for name in CYCLE_SUBDIRS if (cycle_path / name).is_dir()
        ]

        # ── Scenario 2: no subdirs at all ─────────────────────────────────────
        if not present_subdirs:
            _create_subdirs(cycle_path)
            log.info("fresh_start: PASS — subdirectories created: %s", cycle_str)
            return FreshStartResult(
                passed=True,
                cycle_dir=cycle_str,
                notes="subdirectories created",
            )

        # ── Scenario 5: some (but not all) subdirs missing ────────────────────
        if len(present_subdirs) < len(CYCLE_SUBDIRS):
            missing_names: list[str] = [
                name for name in CYCLE_SUBDIRS
                if not (cycle_path / name).is_dir()
            ]
            _create_subdirs(cycle_path)
            log.info(
                "fresh_start: PASS — missing subdirectories created %s: %s",
                missing_names,
                cycle_str,
            )
            return FreshStartResult(
                passed=True,
                cycle_dir=cycle_str,
                missing_subdirs=missing_names,
                notes="missing subdirectories created",
            )

        # ── All 6 subdirs present — check for any files in the tree ──────────
        existing_files = _collect_existing_files(cycle_path)

        # ── Scenario 4: dirty state ───────────────────────────────────────────
        if existing_files:
            log.warning(
                "fresh_start: FAIL — cycle directory is not clean (%d file(s)): %s",
                len(existing_files),
                cycle_str,
            )
            return FreshStartResult(
                passed=False,
                cycle_dir=cycle_str,
                existing_files=existing_files,
                notes="cycle directory is not clean",
            )

        # ── Scenario 3: clean ─────────────────────────────────────────────────
        log.info("fresh_start: PASS — fresh start confirmed: %s", cycle_str)
        return FreshStartResult(
            passed=True,
            cycle_dir=cycle_str,
            notes="fresh start confirmed",
        )

    except Exception as exc:  # noqa: BLE001
        log.error("fresh_start: unexpected error: %s", exc)
        return FreshStartResult(
            passed=False,
            notes=f"unexpected error: {exc}",
        )


def make_cycle_dir(base_dir: str | Path, cycle_number: int) -> Path:
    """Return the expected cycle directory path — no filesystem operations.

    Args:
        base_dir: Root directory under which cycle directories are organised.
        cycle_number: Integer cycle number, zero-padded to three digits in the
            directory name.

    Returns:
        :class:`pathlib.Path` of the form ``<base_dir>/cycle_NNN``.
    """
    return Path(base_dir) / f"cycle_{cycle_number:03d}"
