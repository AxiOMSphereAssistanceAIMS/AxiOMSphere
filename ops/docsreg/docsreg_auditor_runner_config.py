"""
DOCSREG Auditor Runner Configuration Loader.

Loads, validates, and provides access to auditor runtime configuration.
Supports YAML-based configuration with schema validation and sensible defaults.

Usage
-----
from ops.docsreg.docsreg_auditor_runner_config import load_auditor_runner_config

config = load_auditor_runner_config("ops/config/docsreg/auditor_runner.yaml")
print(config.timeout_seconds)  # 300
print(config.min_document_len)  # 1200
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger("docsreg_auditor_runner_config")


@dataclass(frozen=True)
class AuditorRunnerConfig:
    """Immutable auditor runner configuration.

    Attributes
    ----------
    mode : str
        Auditor backend: "noop" or "claude_code"
    timeout_seconds : int
        Subprocess timeout in seconds (default 300)
    min_document_len : int
        Minimum document text length for acceptance (default 1200)
    fallback_quality : float
        Quality score for rejected manifests (default 0.0)
    reject_on_contract_fail : bool
        Whether to fail-closed on contract violation (default True)
    evidence_capture : bool
        Whether to capture and serialize evidence (default True)
    evidence_root : str | Path
        Root directory for evidence packages
    evidence_write_timeout_seconds : int
        Timeout for evidence write operations (default 10)
    """

    mode: str
    timeout_seconds: int
    min_document_len: int
    fallback_quality: float
    reject_on_contract_fail: bool
    evidence_capture: bool
    evidence_root: str | Path
    evidence_write_timeout_seconds: int


# Defaults matching F7 spec
_DEFAULTS: dict[str, Any] = {
    "mode": "noop",
    "timeout_seconds": 300,
    "min_document_len": 1200,
    "fallback_quality": 0.0,
    "reject_on_contract_fail": True,
    "evidence_capture": True,
    "evidence_root": "aims_workspace/docsreg_evidence",
    "evidence_write_timeout_seconds": 10,
}


def validate_auditor_runner_config(config_dict: dict) -> tuple[bool, str]:
    """
    Validate auditor runner configuration dictionary.

    Parameters
    ----------
    config_dict : dict
        Raw configuration dictionary (typically from YAML).

    Returns
    -------
    (is_valid, error_message) : tuple[bool, str]
        (True, "") if valid; (False, reason) if invalid.
    """
    # Check required top-level key
    if "auditor_runner" not in config_dict:
        return False, "missing top-level key: 'auditor_runner'"

    runner_cfg = config_dict["auditor_runner"]
    if not isinstance(runner_cfg, dict):
        return False, f"'auditor_runner' must be dict, got {type(runner_cfg).__name__}"

    # Validate mode
    mode = runner_cfg.get("mode", _DEFAULTS["mode"])
    if mode not in ("noop", "claude_code"):
        return False, f"mode must be 'noop' or 'claude_code', got {mode!r}"

    # Validate timeout_seconds
    timeout = runner_cfg.get("timeout_seconds", _DEFAULTS["timeout_seconds"])
    if not isinstance(timeout, int) or timeout <= 0:
        return (
            False,
            f"timeout_seconds must be positive int, got {timeout!r}",
        )

    # Validate min_document_len
    min_len = runner_cfg.get("min_document_len", _DEFAULTS["min_document_len"])
    if not isinstance(min_len, int) or min_len < 0:
        return (
            False,
            f"min_document_len must be non-negative int, got {min_len!r}",
        )

    # Validate fallback_quality
    fallback_q = runner_cfg.get("fallback_quality", _DEFAULTS["fallback_quality"])
    if not isinstance(fallback_q, (int, float)) or not (0.0 <= fallback_q <= 1.0):
        return (
            False,
            f"fallback_quality must be float in [0.0, 1.0], got {fallback_q!r}",
        )

    # Validate boolean flags
    reject_on_fail = runner_cfg.get(
        "reject_on_contract_fail", _DEFAULTS["reject_on_contract_fail"]
    )
    if not isinstance(reject_on_fail, bool):
        return (
            False,
            f"reject_on_contract_fail must be bool, got {type(reject_on_fail).__name__}",
        )

    evidence_capture = runner_cfg.get(
        "evidence_capture", _DEFAULTS["evidence_capture"]
    )
    if not isinstance(evidence_capture, bool):
        return (
            False,
            f"evidence_capture must be bool, got {type(evidence_capture).__name__}",
        )

    # Validate evidence_root
    evidence_root = runner_cfg.get("evidence_root", _DEFAULTS["evidence_root"])
    if not isinstance(evidence_root, str):
        return (
            False,
            f"evidence_root must be str, got {type(evidence_root).__name__}",
        )

    # Correction 2: Path traversal and safety validation
    try:
        evidence_root_path = Path(evidence_root).resolve()
        evidence_root_str = str(evidence_root_path)
        # Allow only repo-relative, workspace, or /tmp/ paths
        allowed_prefixes = ("/home/", "/workspace/", "/tmp/")
        if not any(evidence_root_str.startswith(p) for p in allowed_prefixes) and not evidence_root_str.startswith("aims_workspace"):
            return (
                False,
                f"evidence_root must be under repo, workspace, or /tmp/; got {evidence_root!r}",
            )
    except (ValueError, OSError) as e:
        return (
            False,
            f"evidence_root path validation failed (traversal attempt?): {evidence_root!r} — {e}",
        )

    # Validate evidence_write_timeout_seconds
    write_timeout = runner_cfg.get(
        "evidence_write_timeout_seconds", _DEFAULTS["evidence_write_timeout_seconds"]
    )
    if not isinstance(write_timeout, int) or write_timeout <= 0:
        return (
            False,
            f"evidence_write_timeout_seconds must be positive int, got {write_timeout!r}",
        )

    # Corrections 3–4: Strict mode enforcement (F11, certification, production contexts)
    if os.getenv("DOCSREG_STRICT_MODE") or os.getenv("F11_EXECUTION"):
        if mode == "noop":
            return (
                False,
                "STRICT_MODE: mode='noop' forbidden; must use mode='claude_code' (real auditor required)",
            )
        if not reject_on_fail:
            return (
                False,
                "STRICT_MODE: reject_on_contract_fail=false forbidden; must be true (fail-closed validation mandatory)",
            )
        if min_len < 1200:
            return (
                False,
                f"STRICT_MODE: min_document_len={min_len} < 1200 forbidden; must be >= 1200 (input contract minimum)",
            )
        if fallback_q != 0.0:
            return (
                False,
                f"STRICT_MODE: fallback_quality={fallback_q} != 0.0 forbidden; must be 0.0 (rejection cannot masquerade as high quality)",
            )

    return True, ""


def load_auditor_runner_config(config_path: str | Path) -> AuditorRunnerConfig:
    """
    Load auditor runner configuration from YAML file.

    Parameters
    ----------
    config_path : str | Path
        Path to auditor_runner.yaml configuration file.

    Returns
    -------
    AuditorRunnerConfig
        Loaded and validated configuration object.

    Raises
    ------
    FileNotFoundError
        If config file does not exist.
    ValueError
        If configuration fails validation.
    yaml.YAMLError
        If YAML parsing fails.
    """
    config_path = Path(config_path)

    if not config_path.exists():
        _log.error("load_auditor_runner_config: config file not found: %s", config_path)
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        if raw_config is None:
            raw_config = {}
    except yaml.YAMLError as e:
        _log.error("load_auditor_runner_config: YAML parse error: %s", e)
        raise

    # Validate
    is_valid, error_msg = validate_auditor_runner_config(raw_config)
    if not is_valid:
        _log.error("load_auditor_runner_config: validation failed: %s", error_msg)
        raise ValueError(f"Configuration validation failed: {error_msg}")

    # Extract and merge with defaults
    runner_cfg = raw_config.get("auditor_runner", {})
    config_dict = {
        "mode": runner_cfg.get("mode", _DEFAULTS["mode"]),
        "timeout_seconds": runner_cfg.get("timeout_seconds", _DEFAULTS["timeout_seconds"]),
        "min_document_len": runner_cfg.get(
            "min_document_len", _DEFAULTS["min_document_len"]
        ),
        "fallback_quality": runner_cfg.get(
            "fallback_quality", _DEFAULTS["fallback_quality"]
        ),
        "reject_on_contract_fail": runner_cfg.get(
            "reject_on_contract_fail", _DEFAULTS["reject_on_contract_fail"]
        ),
        "evidence_capture": runner_cfg.get(
            "evidence_capture", _DEFAULTS["evidence_capture"]
        ),
        "evidence_root": runner_cfg.get("evidence_root", _DEFAULTS["evidence_root"]),
        "evidence_write_timeout_seconds": runner_cfg.get(
            "evidence_write_timeout_seconds", _DEFAULTS["evidence_write_timeout_seconds"]
        ),
    }

    _log.info(
        "load_auditor_runner_config: loaded config from %s (mode=%r, timeout=%d, "
        "min_len=%d, evidence_capture=%s)",
        config_path,
        config_dict["mode"],
        config_dict["timeout_seconds"],
        config_dict["min_document_len"],
        config_dict["evidence_capture"],
    )

    return AuditorRunnerConfig(**config_dict)


def get_default_config() -> AuditorRunnerConfig:
    """
    Get default auditor runner configuration.

    Returns
    -------
    AuditorRunnerConfig
        Configuration with all default values.
    """
    return AuditorRunnerConfig(**_DEFAULTS)  # type: ignore
