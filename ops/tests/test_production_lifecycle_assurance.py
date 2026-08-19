from ops.policy_evolution.production_lifecycle_assurance import run_lifecycle_assurance


def test_production_lifecycle_assurance_scale_and_replay(tmp_path):
    result = run_lifecycle_assurance(tmp_path, backlog=10, evidence_refs=100)
    assert result["one_cas_winner_each"] is True
    assert result["duplicate_reconciled"] is True
    assert result["crash_replay_preserved_queue"] is True
    assert result["evidence_references"] == 1000
    assert result["production_mutation"] is False
