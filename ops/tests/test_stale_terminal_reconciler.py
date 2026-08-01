from __future__ import annotations

import json

from ops.self_learning.stale_terminal_reconciler import reconcile_stale_packages


def test_stale_reconciliation_preserves_evidence_without_success(tmp_path):
    session = tmp_path / "s"
    session.mkdir()
    (session / "session_manifest.json").write_text(json.dumps({"status": "RUNNING", "pid": 99999}) + "\n")
    result = reconcile_stale_packages([session], set())
    row = result["results"][0]
    assert row["resulting_disposition"] == "STALE_INCOMPLETE_EVIDENCE_PRESERVED"
    assert row["terminal_status_fabricated"] is False
    assert result["deletion_performed"] is False
