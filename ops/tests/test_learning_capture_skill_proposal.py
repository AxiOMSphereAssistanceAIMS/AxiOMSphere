from __future__ import annotations

import json
from pathlib import Path

from ops.learning_capture.skill_proposal_builder import create_or_update_skill_proposal


def test_skill_proposal_created_for_reusable_failure(tmp_path: Path) -> None:
    proposal = create_or_update_skill_proposal(
        output_root=tmp_path,
        case_id="case-1",
        failure_modes=["evidence_only_completion_without_feature_implementation"],
    )
    assert proposal is not None
    assert proposal["skill_name"] == "docsreg-feature-completion-verification"
    md_path = Path(proposal["markdown_path"])
    assert md_path.exists()
    assert "Verify production files exist in repo" in md_path.read_text(encoding="utf-8")
    data = json.loads(Path(proposal["json_path"]).read_text(encoding="utf-8"))
    assert data["approved_for_training"] is False
    assert data["requires_human_approval"] is True
