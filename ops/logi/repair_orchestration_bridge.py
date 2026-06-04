from __future__ import annotations

from pathlib import Path
from typing import Any

from repairman.repair_loop import RepairLoop
from repairman.repair_registry import StepExecution, write_json


def run_logi_style_repair_step(run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    missing = run_dir / "expected" / "artifact.json"

    def executor(_step: StepExecution, _attempt: int) -> dict[str, Any]:
        if missing.exists():
            return {"status": "PASS", "stdout": "artifact exists", "stderr": ""}
        return {
            "status": "FAIL",
            "stdout": "",
            "stderr": "missing expected artifact",
            "failure_type": "MISSING_ARTIFACT",
            "recommended_repair": "create_missing_output_directory",
            "suspected_root_cause": "Expected artifact file is absent.",
        }

    def repair_executor(repair_type: str, _step: StepExecution, _failure) -> dict[str, Any]:
        if repair_type == "create_missing_output_directory":
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.write_text('{"ok":true}\n', encoding="utf-8")
            return {
                "ok": True,
                "description": "Created missing artifact for retry.",
                "files_changed": [],
                "artifacts_created": [str(missing)],
                "repair_command_or_callable": "mkdir/write expected artifact",
            }
        return {"ok": False, "description": "Unsupported repair type in bridge."}

    def validator(_step: StepExecution, _attempt: int) -> dict[str, Any]:
        return {"status": "PASS" if missing.exists() else "FAIL", "evidence_path": str(missing)}

    loop = RepairLoop(run_dir, task_id="logi_control_plane_like", owner_agent="logi")
    step = StepExecution(
        step_id="integration_step_001",
        task_id="logi_control_plane_like",
        owner_agent="logi",
        executor="repair_loop_executor",
        command_or_callable="integration_callable",
        expected_artifacts=[str(missing)],
        acceptance_criteria=["Expected artifact exists after retry"],
    )

    out = loop.run_step(
        step,
        executor=executor,
        repair_executor=repair_executor,
        validator=validator,
        repair_type_selector=lambda _f: "create_missing_output_directory",
    )
    result = out.to_dict()
    write_json(run_dir / "integration_result.json", result)
    return result

