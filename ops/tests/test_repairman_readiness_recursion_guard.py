from ops.orchestrator_planning import repairman_readiness_support as module


def test_artifact_build_never_reenters_night_certification(monkeypatch):
    monkeypatch.setattr(
        module,
        "run_repairman_night_certification_with_hermes_repair",
        lambda **_: (_ for _ in ()).throw(AssertionError("recursive call")),
    )

    result = module._run_nested_night_certification()

    assert result["final_status"] == "NOT_RUN_FROM_ARTIFACT_BUILD"
    assert result["controlled_failure_exercised"] is True
