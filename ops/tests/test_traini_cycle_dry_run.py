from ops.ft.traini import traini_cycle


def test_step_train_dry_run_never_invokes_training(monkeypatch):
    def forbidden_run(*args, **kwargs):
        raise AssertionError("training subprocess must not run in dry-run")

    monkeypatch.setattr(traini_cycle, "_run", forbidden_run)
    result = traini_cycle._step_train(
        "14",
        {"ft_script": "ops/ft/scripts/run_v19_slot14.sh"},
        dry_run=True,
        skip_train=False,
    )

    assert result["status"] == "DRY_RUN"
    assert "not invoked" in result["reason"]
