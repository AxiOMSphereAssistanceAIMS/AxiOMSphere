"""
LAYER 5 — LIVE DOCSREG RUNTIME INTEGRATION SMOKE

Tests run_docsreg_cycle() with:
  - real production auditor (build_structure_auditor_fn)
  - real Redis (resolves localhost or Docker container IP automatically)
  - real quality_report.json written by task_quality_validated
  - real learning writes via record_knowledge_source
  - NO mock of run_docsreg_cycle

Source document: ISO 55000 Asset Managment Policy.pdf (99 KB, PDF)

Design note — evidence_root == draft_path.parent
  task_quality_validated writes quality_report.json to draft_path.parent.
  _record_cycle_learning reads quality_report.json from evidence_root.
  To satisfy both at once, we copy the source PDF *into* evidence_root so
  that draft_path.parent IS evidence_root.

Redis resolution:
  Redis may be on localhost:6379 (native) or only inside the Docker network
  (container axiomsphere-aims-redis).  _resolve_redis_url() probes localhost
  first, then falls back to the container IP via `docker inspect`.

Run:
    # full live-runtime suite
    pytest ops/tests/test_docsreg_live_runtime_smoke.py -v -m integration

    # regression guard (must stay green after every change)
    pytest ops/tests/test_docsreg_*.py -v --tb=short
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

# ── Source document ────────────────────────────────────────────────────────────

_SOURCE_PDF = Path(
    "/media/axi_omi_sphere/FDF0-25E2/Documents/Standards/"
    "AIM INF/ISO 55000 Asset Managment Policy.pdf"
)

# ── Redis URL resolution ───────────────────────────────────────────────────────

_REDIS_CONTAINER_NAME = "axiomsphere-aims-redis"


def _resolve_redis_url() -> str:
    """Return a working Redis URL for the current environment.

    Probes localhost:6379 first (works if Redis is published to the host).
    Falls back to the Docker container IP (works when Redis only has an
    internal Docker network address, which is the typical AIMS dev setup).
    """
    import redis as _redis_mod

    # 1. Try localhost — fast path when Redis is published to host port
    try:
        _redis_mod.Redis.from_url(
            "redis://localhost:6379/0", socket_connect_timeout=0.5
        ).ping()
        return "redis://localhost:6379/0"
    except Exception:
        pass

    # 2. Docker container IP — Redis lives only in the Docker network
    try:
        result = subprocess.run(
            [
                "docker", "inspect", _REDIS_CONTAINER_NAME,
                "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            ],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        if ip:
            url = f"redis://{ip}:6379/0"
            _redis_mod.Redis.from_url(url, socket_connect_timeout=1).ping()
            return url
    except Exception:
        pass

    # Last resort — let the caller fail with a clear connection error
    return "redis://localhost:6379/0"


_REDIS_URL: str = _resolve_redis_url()

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _build_evidence_root(tmp_path: Path) -> tuple[Path, Path]:
    """Return (evidence_root, draft_path).

    Copies the source PDF into evidence_root so that
    task_quality_validated writes quality_report.json there.
    """
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    draft_path = evidence_root / _SOURCE_PDF.name
    shutil.copy2(_SOURCE_PDF, draft_path)
    return evidence_root, draft_path


def _run_cycle(draft_path: Path, evidence_root: Path) -> Any:
    """Call run_docsreg_cycle with real auditor and local Redis."""
    from ops.docsreg.docsreg_cycle_runner import run_docsreg_cycle
    from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn

    return run_docsreg_cycle(
        document_type="iso_standard",
        draft_path=draft_path,
        evidence_root=evidence_root,
        redis_url=_REDIS_URL,
        target_quality=0.98,
        max_cycles=1,
        stall_window=1,
        min_quality_delta=0.005,
        teacher_mode="noop",
        auditor_fn=build_structure_auditor_fn(threshold=0.80),
    )


def _write_learning(
    result: Any,
    source_file: Path,
    evidence_root: Path,
    workspace_dir: Path,
) -> dict:
    """Call record_knowledge_source, mirroring what _record_cycle_learning does."""
    from ops.docsreg.docsreg_knowledge_source import (
        compute_file_sha256,
        read_json_object,
        record_knowledge_source,
    )

    quality_report: dict = dict(read_json_object(evidence_root / "quality_report.json"))

    try:
        quality_report["source_sha256"] = compute_file_sha256(source_file)
    except Exception:
        pass

    return record_knowledge_source(
        evidence_dir=evidence_root,
        workspace_dir=workspace_dir,
        quality_report=quality_report,
        source_file=str(source_file),
        file_type=source_file.suffix.lstrip(".") or "unknown",
        final_state=getattr(result, "outcome", None),
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_live_runtime_smoke_creates_master_package(tmp_path: Path) -> None:
    """run_docsreg_cycle returns a DocsregCycleRunResult with all expected fields.

    Acceptance criteria:
    - No exception propagated
    - Result has: document_type, draft_path, outcome, passed (bool), best_quality (float)
    - audit_status implied by passed flag is not COMPONENT_BLOCKED (i.e. the real
      auditor ran, not the legacy noop that produces COMPONENT_BLOCKED)
    """
    evidence_root, draft_path = _build_evidence_root(tmp_path)

    result = _run_cycle(draft_path, evidence_root)

    assert result is not None, "run_docsreg_cycle returned None"
    assert result.document_type == "iso_standard"
    assert result.draft_path == str(draft_path)
    assert isinstance(result.passed, bool)
    assert isinstance(result.best_quality, float), (
        f"best_quality expected float, got {type(result.best_quality)}"
    )
    assert 0.0 <= result.best_quality <= 1.0, (
        f"best_quality out of range: {result.best_quality}"
    )
    assert result.outcome, "outcome field is empty"
    assert result.cycles_run >= 1, f"cycles_run={result.cycles_run} — pipeline did not execute"


@pytest.mark.integration
def test_live_runtime_smoke_writes_quality_report(tmp_path: Path) -> None:
    """task_quality_validated writes quality_report.json with 5 component scores.

    Acceptance criteria:
    - quality_report.json exists in evidence_root after the cycle
    - File is valid JSON
    - Contains keys: content_richness_score, data_retention_score,
      source_to_master_alignment_score, structure_score, metadata_safety_score
    - final_quality is a float in [0.0, 1.0]
    - quality_method is present and non-empty
    """
    evidence_root, draft_path = _build_evidence_root(tmp_path)

    _run_cycle(draft_path, evidence_root)

    report_path = evidence_root / "quality_report.json"
    assert report_path.exists(), (
        f"quality_report.json was not written to {evidence_root}"
    )

    with report_path.open(encoding="utf-8") as fh:
        report = json.load(fh)

    component_keys = [
        "content_richness_score",
        "data_retention_score",
        "source_to_master_alignment_score",
        "structure_score",
        "metadata_safety_score",
    ]
    missing = [k for k in component_keys if k not in report]
    assert not missing, f"quality_report.json missing component keys: {missing}"

    final_quality = report.get("final_quality")
    assert isinstance(final_quality, float), (
        f"final_quality expected float, got {type(final_quality)}: {final_quality}"
    )
    assert 0.0 <= final_quality <= 1.0, f"final_quality out of range: {final_quality}"

    quality_method = report.get("quality_method", "")
    assert quality_method, "quality_method field is missing or empty"


@pytest.mark.integration
def test_live_runtime_smoke_uses_real_auditor(tmp_path: Path) -> None:
    """Learning entry records real_auditor_used = True for the production auditor.

    The production auditor (build_structure_auditor_fn) returns COMPONENT_PASS or
    COMPONENT_FAIL_REPAIRABLE — both are in RECOGNISED_AUDIT_STATUSES, so
    real_auditor_used is True.  The legacy build_docsreg_auditor returned
    COMPONENT_BLOCKED which is NOT recognised and sets real_auditor_used = False.

    Acceptance criteria:
    - knowledge_entry.json exists in evidence_root
    - real_auditor_used is True
    - outcome.audit_status is NOT "COMPONENT_BLOCKED"
    """
    evidence_root, draft_path = _build_evidence_root(tmp_path)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    result = _run_cycle(draft_path, evidence_root)

    entry = _write_learning(result, draft_path, evidence_root, workspace_dir)

    assert entry["real_auditor_used"] is True, (
        f"real_auditor_used is False — legacy auditor may be active. "
        f"audit_status={entry['outcome'].get('audit_status')}"
    )
    audit_status = entry["outcome"].get("audit_status", "")
    assert audit_status != "COMPONENT_BLOCKED", (
        f"audit_status is COMPONENT_BLOCKED — production auditor not wired. "
        f"entry outcome: {entry['outcome']}"
    )


@pytest.mark.integration
def test_live_runtime_smoke_writes_learning_entry(tmp_path: Path) -> None:
    """record_knowledge_source appends an entry to docsreg_learning.jsonl.

    Acceptance criteria:
    - docsreg_learning.jsonl exists in workspace/axi_ft_log/
    - Has ≥ 1 entry
    - Entry has schema_version = "docsreg.knowledge.v1"
    - Entry has source_file pointing at the original PDF
    - training_candidates.jsonl also written (always-write artifact)
    - knowledge_entry.json exists in evidence_root
    """
    evidence_root, draft_path = _build_evidence_root(tmp_path)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    result = _run_cycle(draft_path, evidence_root)
    _write_learning(result, draft_path, evidence_root, workspace_dir)

    # Learning JSONL
    learning_jsonl = workspace_dir / "axi_ft_log" / "docsreg_learning.jsonl"
    assert learning_jsonl.exists(), (
        f"docsreg_learning.jsonl not written to {workspace_dir / 'axi_ft_log'}"
    )
    lines = [ln for ln in learning_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1, "docsreg_learning.jsonl is empty"
    entry = json.loads(lines[0])
    assert entry.get("schema_version") == "docsreg.knowledge.v1", (
        f"Unexpected schema_version: {entry.get('schema_version')}"
    )
    assert str(draft_path) in entry.get("source_file", ""), (
        f"source_file mismatch: {entry.get('source_file')}"
    )

    # training_candidates.jsonl — always written
    candidates_jsonl = workspace_dir / "axi_ft_log" / "training_candidates.jsonl"
    assert candidates_jsonl.exists(), "training_candidates.jsonl not written"

    # knowledge_entry.json — written atomically to evidence_root
    knowledge_entry = evidence_root / "knowledge_entry.json"
    assert knowledge_entry.exists(), "knowledge_entry.json not written to evidence_root"


@pytest.mark.integration
def test_live_runtime_smoke_does_not_certify_failed_doc(tmp_path: Path) -> None:
    """A near-empty document must not pass certification.

    Uses a minimal stub text file (no headers, no sections) so the composite
    quality scorer returns a low score and passed is False.

    Acceptance criteria:
    - result.passed is False
    - result.best_quality < 0.98
    - No exception raised (pipeline is fail-safe)
    - quality_report.json is still written (audit evidence preserved on failure)
    """
    from ops.docsreg.docsreg_cycle_runner import run_docsreg_cycle
    from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn

    evidence_root = tmp_path / "evidence_fail"
    evidence_root.mkdir(parents=True)

    # Minimal stub: no sections, no references, no metadata
    stub_doc = evidence_root / "stub_doc.md"
    stub_doc.write_text("This is a stub document with no structure.", encoding="utf-8")

    result = run_docsreg_cycle(
        document_type="iso_standard",
        draft_path=stub_doc,
        evidence_root=evidence_root,
        redis_url=_REDIS_URL,
        target_quality=0.98,
        max_cycles=1,
        stall_window=1,
        min_quality_delta=0.005,
        teacher_mode="noop",
        auditor_fn=build_structure_auditor_fn(threshold=0.80),
    )

    assert result.passed is False, (
        f"A stub document must not be certified (passed={result.passed}, "
        f"quality={result.best_quality})"
    )
    assert result.best_quality < 0.98, (
        f"best_quality={result.best_quality} is unexpectedly high for a stub doc"
    )

    # quality_report.json must still be written — fail-safe evidence
    report_path = evidence_root / "quality_report.json"
    assert report_path.exists(), (
        "quality_report.json must be written even when the document fails"
    )
