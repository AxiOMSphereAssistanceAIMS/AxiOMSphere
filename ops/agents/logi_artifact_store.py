"""
logi_artifact_store.py

Per-skill artifact writer for Logi chief-engineer process skills.

Extends the convention used by ops/logi/artifact_fallback_writer.py
but writes to per-skill subdirectories under aims_workspace/logi_artifacts/.

Artifact paths:
  aims_workspace/logi_artifacts/<skill_id>/<timestamp>_<short_id>.json
  aims_workspace/logi_artifacts/<skill_id>/<timestamp>_<short_id>.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACTS_DIR = _ROOT / "aims_workspace" / "logi_artifacts"


@dataclass
class SkillArtifact:
    artifact_id: str
    skill_id: str
    role: str
    source_message: str
    created_at: str
    user_id: str
    chat_id: str
    input: dict
    output: dict
    assumptions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    next_recommended_skills: list[str] = field(default_factory=list)
    status: str = "PASSED"
    failure_class: str | None = None
    learning_event_candidate: bool = False


def _short_id(skill_id: str, ts: str) -> str:
    raw = f"{skill_id}:{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def write_skill_artifact(
    skill_id: str,
    source_message: str,
    output: dict,
    user_id: str = "0",
    chat_id: str = "0",
    role: str = "skill_output",
    assumptions: list[str] | None = None,
    evidence: list[str] | None = None,
    next_recommended_skills: list[str] | None = None,
    status: str = "PASSED",
    failure_class: str | None = None,
    learning_event_candidate: bool = False,
) -> SkillArtifact:
    """Write a skill artifact to disk and return the artifact object."""
    now = datetime.now(timezone.utc).isoformat()
    short = _short_id(skill_id, now)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_id = f"{skill_id}_{ts}_{short}"

    artifact = SkillArtifact(
        artifact_id=artifact_id,
        skill_id=skill_id,
        role=role,
        source_message=source_message,
        created_at=now,
        user_id=user_id,
        chat_id=chat_id,
        input={"message": source_message},
        output=output,
        assumptions=assumptions or [],
        evidence=evidence or [],
        next_recommended_skills=next_recommended_skills or [],
        status=status,
        failure_class=failure_class,
        learning_event_candidate=learning_event_candidate,
    )

    skill_dir = _ARTIFACTS_DIR / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    json_path = skill_dir / f"{ts}_{short}.json"
    json_path.write_text(
        json.dumps(asdict(artifact), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return artifact


def load_latest_artifact(skill_id: str) -> dict | None:
    """Return the most recent artifact dict for a skill, or None."""
    skill_dir = _ARTIFACTS_DIR / skill_id
    if not skill_dir.exists():
        return None
    candidates = sorted(skill_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception:
        return None
