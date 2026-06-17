import json

from ops.docagent import doc_skills


def test_local_score_quarantines_candidate_instead_of_saving_gold(
    monkeypatch,
    tmp_path,
) -> None:
    candidate_path = tmp_path / "document_training_candidates.jsonl"
    monkeypatch.setattr(
        doc_skills,
        "_TRAINING_CANDIDATES",
        candidate_path,
    )

    saved = doc_skills._quarantine_training_candidate(
        "generate",
        "Asset Integrity Policy",
        "Generated document",
        0.92,
    )

    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert saved
    assert payload["status"] == "CANDIDATE_NOT_TRAINING_DATA"
    assert payload["local_score"] == 0.92
    assert "claude_teacher_quality_pass" in payload["required_gates"]
    assert "baseline_holdout_benchmark_win" in payload["required_gates"]
