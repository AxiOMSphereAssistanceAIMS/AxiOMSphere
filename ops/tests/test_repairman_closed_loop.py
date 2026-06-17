from pathlib import Path

from repairman.api_closed_loop import run_closed_repair


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    target = project / "ops" / "sample.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 'before'\n", encoding="utf-8")
    return project, target


def test_successful_repair_validates_and_captures_learning(tmp_path):
    project, target = _project(tmp_path)
    run_dir = tmp_path / "run"
    memory_dir = tmp_path / "memory"

    result = run_closed_repair(
        task_id="success",
        owner_agent="test",
        run_dir=run_dir,
        cwd=project,
        repair_command=[
            "python",
            "-c",
            "from pathlib import Path; Path('ops/sample.py').write_text(\"VALUE = 'after'\\n\")",
        ],
        validation_command=[
            "python",
            "-c",
            "from pathlib import Path; assert \"after\" in Path('ops/sample.py').read_text()",
        ],
        rollback_command=[],
        memory_dir=memory_dir,
    )

    assert result["status"] == "PASS"
    assert "after" in target.read_text()
    assert (memory_dir / "repairman_pairs_auto.jsonl").exists()
    assert (memory_dir / "lessons.jsonl").exists()


def test_failed_validation_rolls_back_snapshot(tmp_path):
    project, target = _project(tmp_path)

    result = run_closed_repair(
        task_id="rollback",
        owner_agent="test",
        run_dir=tmp_path / "run",
        cwd=project,
        repair_command=[
            "python",
            "-c",
            "from pathlib import Path; Path('ops/sample.py').write_text(\"VALUE = 'broken'\\n\")",
        ],
        validation_command=["python", "-c", "raise SystemExit(1)"],
        rollback_command=[],
        memory_dir=tmp_path / "memory",
    )

    assert result["status"] == "ROLLED_BACK"
    assert target.read_text() == "VALUE = 'before'\n"
    assert result["rollback_result"]["status"] == "PASS"


def test_structured_model_patch_is_applied_before_validation(tmp_path):
    project, target = _project(tmp_path)
    payload = {
        "root_cause": "fixture",
        "files_changed": ["ops/sample.py"],
        "patch_diff": (
            "--- a/ops/sample.py\n"
            "+++ b/ops/sample.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 'before'\n"
            "+VALUE = 'patched'\n"
        ),
        "tests_run": [],
        "test_result": "not_run",
        "risk_level": "low",
        "rollback_notes": "snapshot rollback",
    }

    result = run_closed_repair(
        task_id="model_patch",
        owner_agent="test",
        run_dir=tmp_path / "run",
        cwd=project,
        repair_command=["python", "-c", f"import json; print(json.dumps({payload!r}))"],
        validation_command=[
            "python",
            "-c",
            "from pathlib import Path; assert \"patched\" in Path('ops/sample.py').read_text()",
        ],
        rollback_command=[],
        memory_dir=tmp_path / "memory",
    )

    assert result["status"] == "PASS"
    assert target.read_text() == "VALUE = 'patched'\n"
