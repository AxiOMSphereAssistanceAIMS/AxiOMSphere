from __future__ import annotations

import fcntl
import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "ft"
    / "scripts"
    / "build_dataset_v20_synth.py"
)
SPEC = importlib.util.spec_from_file_location("build_dataset_v20_synth", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_jsonl(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(count):
            handle.write(json.dumps({"_action": "classify_doc", "index": index}) + "\n")


def test_run_lock_is_exclusive(tmp_path: Path) -> None:
    output = tmp_path / "synth.jsonl"
    first = MODULE._acquire_run_lock(output)
    try:
        second = (tmp_path / "synth.jsonl.lock").open("a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("second process unexpectedly acquired synthesis lock")
        finally:
            second.close()
    finally:
        first.close()


def test_checkpoint_is_verified_copy(tmp_path: Path) -> None:
    output = tmp_path / "synth.jsonl"
    _write_jsonl(output, 3)

    checkpoint = MODULE._checkpoint_before_resume(output, 3)

    assert checkpoint.exists()
    assert checkpoint.read_bytes() == output.read_bytes()
    assert MODULE._validate_jsonl(checkpoint) == 3


def test_invalid_jsonl_blocks_resume(tmp_path: Path) -> None:
    output = tmp_path / "synth.jsonl"
    output.write_text('{"valid": true}\nnot-json\n', encoding="utf-8")

    try:
        MODULE._validate_jsonl(output)
    except RuntimeError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("invalid JSONL was accepted")


def test_existing_output_requires_resume(tmp_path: Path) -> None:
    output = tmp_path / "synth.jsonl"
    _write_jsonl(output, 1)

    try:
        MODULE._require_safe_output_mode(output, resume=False)
    except RuntimeError as exc:
        assert "--resume" in str(exc)
    else:
        raise AssertionError("existing synthesis output could be overwritten")

    MODULE._require_safe_output_mode(output, resume=True)
