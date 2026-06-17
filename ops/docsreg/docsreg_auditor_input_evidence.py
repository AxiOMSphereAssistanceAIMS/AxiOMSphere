"""
DOCSREG Auditor Evidence Capture.

Serialize all intermediate states (input, output, subprocess) for debugging.
Atomic write to JSON for full cycle reconstruction.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("docsreg_auditor_input_evidence")


def capture_auditor_input_state(manifest: dict, doc_type: str) -> dict:
    """
    Serialize auditor input state.

    Parameters
    ----------
    manifest : dict
        Manifest passed to auditor_fn.
    doc_type : str
        Document type identifier.

    Returns
    -------
    dict
        Serialized input state: {
            "timestamp": ISO8601,
            "document_type": doc_type,
            "manifest_keys": [...],
            "document_text_len": N,
            "document_text_preview": "first 200 chars...",
        }
    """
    doc_text = manifest.get("document_text", "") if isinstance(manifest, dict) else ""
    manifest_keys = list(manifest.keys()) if isinstance(manifest, dict) else []

    preview = doc_text[:200].replace("\n", "\\n") if doc_text else ""

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "document_type": doc_type,
        "manifest_keys": manifest_keys,
        "document_text_len": len(doc_text),
        "document_text_preview": preview,
    }


def capture_auditor_output_state(result: dict) -> dict:
    """
    Serialize auditor output state.

    Parameters
    ----------
    result : dict
        Auditor result: {"status", "quality", "notes", "error", ...}

    Returns
    -------
    dict
        Serialized output state: {
            "timestamp": ISO8601,
            "status": result["status"],
            "quality": result["quality"],
            "notes": result.get("notes", ""),
            "error": result.get("error"),
            "error_present": bool,
        }
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status", "UNKNOWN"),
        "quality": result.get("quality", 0.0),
        "notes": result.get("notes", ""),
        "error": result.get("error"),
        "error_present": result.get("error") is not None,
    }


def capture_subprocess_state(
    command: str,
    prompt_len: int,
    timeout: int,
    stdout: str,
    exit_code: int,
    execution_time: float,
) -> dict:
    """
    Serialize subprocess invocation state.

    Parameters
    ----------
    command : str
        Subprocess command (e.g. "/path/to/claude").
    prompt_len : int
        Length of prompt passed to subprocess.
    timeout : int
        Timeout in seconds.
    stdout : str
        Subprocess stdout.
    exit_code : int
        Process exit code.
    execution_time : float
        Execution time in seconds.

    Returns
    -------
    dict
        Serialized subprocess state: {
            "timestamp": ISO8601,
            "command": command,
            "prompt_len": prompt_len,
            "timeout_seconds": timeout,
            "stdout_len": len(stdout),
            "stdout_preview": "first 300 chars...",
            "exit_code": exit_code,
            "execution_time": execution_time,
        }
    """
    preview = stdout[:300].replace("\n", "\\n") if stdout else ""

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "prompt_len": prompt_len,
        "timeout_seconds": timeout,
        "stdout_len": len(stdout),
        "stdout_preview": preview,
        "exit_code": exit_code,
        "execution_time": execution_time,
    }


def write_evidence_package(
    doc_type: str,
    cycle_id: str,
    states: dict,
    evidence_root: str | Path,
) -> Path:
    """
    Atomically write evidence package to disk.

    Parameters
    ----------
    doc_type : str
        Document type identifier.
    cycle_id : str
        Cycle identifier (e.g. "API_cycle000_20260611_112902_5bebc641").
    states : dict
        Evidence state dict: {
            "input": capture_auditor_input_state() result,
            "output": capture_auditor_output_state() result,
            "subprocess": capture_subprocess_state() result,  # optional
        }
    evidence_root : str | Path
        Root directory for evidence.

    Returns
    -------
    Path
        Path to written evidence JSON file.

    Raises
    ------
    OSError
        If write fails.
    """
    evidence_root = Path(evidence_root)
    cycle_dir = evidence_root / doc_type / cycle_id

    try:
        cycle_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log.error(
            "write_evidence_package: failed to create cycle_dir=%s: %s",
            cycle_dir,
            e,
        )
        raise

    evidence_file = cycle_dir / "auditor_evidence.json"

    # Add metadata
    package = {
        "cycle_id": cycle_id,
        "document_type": doc_type,
        "evidence_timestamp": datetime.now(timezone.utc).isoformat(),
        "states": states,
    }

    try:
        with open(evidence_file, "w") as f:
            json.dump(package, f, indent=2)
        _log.info(
            "write_evidence_package: wrote evidence_file=%s (size=%d bytes)",
            evidence_file,
            evidence_file.stat().st_size,
        )
        return evidence_file
    except (OSError, IOError) as e:
        _log.error(
            "write_evidence_package: failed to write evidence_file=%s: %s",
            evidence_file,
            e,
        )
        raise


def read_evidence_package(evidence_file: str | Path) -> dict | None:
    """
    Read evidence package from disk.

    Parameters
    ----------
    evidence_file : str | Path
        Path to auditor_evidence.json.

    Returns
    -------
    dict | None
        Deserialized evidence package, or None if file not found or parse fails.
    """
    evidence_file = Path(evidence_file)
    if not evidence_file.exists():
        _log.warning("read_evidence_package: file not found: %s", evidence_file)
        return None

    try:
        with open(evidence_file) as f:
            package = json.load(f)
        _log.debug("read_evidence_package: loaded evidence_file=%s", evidence_file)
        return package
    except (OSError, IOError, json.JSONDecodeError) as e:
        _log.error(
            "read_evidence_package: failed to read evidence_file=%s: %s",
            evidence_file,
            e,
        )
        return None
