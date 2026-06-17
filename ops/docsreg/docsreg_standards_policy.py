"""
Standalone loader for DOCSREG approved standards policy.

Loads ``config/docsreg/approved_standards_policy.yaml`` once at import time and
exports three module-level constants consumed by the reference governance gate
and any other certification module that needs standards classification.

Exports
-------
REFERENCE_STANDARDS : frozenset[str]
    Standards whose presence in a document is always VERIFIED.
FABRICATED_STANDARDS_PATTERNS : list[str]
    Python regex patterns (re.IGNORECASE) for standards that block certification.
ISO_PREFIXES : tuple[str, ...]
    Canonical ISO prefix strings for verified-classification prefix matching.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ops.docsreg.standards_registry import (
    list_registered_standards,
    register_standards,
)

log = logging.getLogger("docsreg_standards_policy")

# ── Policy file path ───────────────────────────────────────────────────────────
# parents[0] = ops/docsreg/
# parents[1] = ops/
# parents[2] = repo root
_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "docsreg"
    / "approved_standards_policy.yaml"
)

# ── Hardcoded defaults (used when YAML is missing or malformed) ────────────────

_DEFAULT_REFERENCE_STANDARDS: frozenset[str] = frozenset([
    "ISO 9000",
    "ISO 55001",
    "ISO 55002",
    "ISO 45001",   # Occupational Health & Safety Management Systems — legitimate in AIM-PFM context
    "ISO 9712",    # Non-Destructive Testing — Qualification/certification — legitimate in asset integrity
])

_DEFAULT_FABRICATED_PATTERNS: list[str] = [
    r"API\s+(?:510|570|580|581|RP\s*571|RP\s*572|RP\s*574)",
    r"NACE\s+SP\d{4}",
    r"IEC\s+60364",
    r"NFPA\s+70",
    r"ASME\s+B31\.\d",
    r"AS\s*4024",
    r"BS\s*EN\s+ISO\s+14001",
]

_DEFAULT_ISO_PREFIXES: tuple[str, ...] = (
    "ISO 9000", "ISO 55001", "ISO 55002", "ISO 45001", "ISO 9712"
)


def load_policy() -> tuple[frozenset[str], list[str], tuple[str, ...]]:
    """Load approved standards policy from YAML.

    Returns
    -------
    tuple
        ``(reference_standards, fabricated_patterns, iso_prefixes)``

    Falls back to hardcoded defaults if PyYAML is unavailable or the file is
    missing / malformed — never raises.
    """
    try:
        import yaml
    except ImportError:
        log.warning("PyYAML not available — using hardcoded approved standards policy")
        register_standards(
            _DEFAULT_REFERENCE_STANDARDS,
            domain="docsreg.reference_policy",
            source="docsreg_standards_policy.bootstrap",
            status="approved",
        )
        return _DEFAULT_REFERENCE_STANDARDS, _DEFAULT_FABRICATED_PATTERNS, _DEFAULT_ISO_PREFIXES

    try:
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        required_keys = ("reference_standards", "fabricated_patterns", "iso_prefixes")
        missing = [k for k in required_keys if k not in (data or {})]
        if missing:
            log.warning(
                "Policy YAML at %s missing required keys %s — using hardcoded defaults",
                _POLICY_PATH,
                missing,
            )
            register_standards(
                _DEFAULT_REFERENCE_STANDARDS,
                domain="docsreg.reference_policy",
                source="docsreg_standards_policy.bootstrap",
                status="approved",
            )
            return _DEFAULT_REFERENCE_STANDARDS, _DEFAULT_FABRICATED_PATTERNS, _DEFAULT_ISO_PREFIXES
        reference_standards = frozenset(data["reference_standards"])
        fabricated_patterns = list(data["fabricated_patterns"])
        iso_prefixes = tuple(data["iso_prefixes"])
        register_standards(
            reference_standards,
            domain="docsreg.reference_policy",
            source="config/docsreg/approved_standards_policy.yaml",
            status="approved",
        )
        registered_reference_standards = list_registered_standards(
            domain="docsreg.reference_policy"
        )
        if registered_reference_standards:
            reference_standards = frozenset(registered_reference_standards)
        log.debug("Approved standards policy loaded from %s", _POLICY_PATH)
        return reference_standards, fabricated_patterns, iso_prefixes
    except FileNotFoundError:
        log.warning(
            "Approved standards policy file not found at %s — using hardcoded defaults",
            _POLICY_PATH,
        )
    except Exception as exc:
        log.warning(
            "Failed to load approved standards policy from %s: %s — using hardcoded defaults",
            _POLICY_PATH,
            exc,
        )
    register_standards(
        _DEFAULT_REFERENCE_STANDARDS,
        domain="docsreg.reference_policy",
        source="docsreg_standards_policy.bootstrap",
        status="approved",
    )
    return _DEFAULT_REFERENCE_STANDARDS, _DEFAULT_FABRICATED_PATTERNS, _DEFAULT_ISO_PREFIXES


# ── Module-level exports loaded once at import time ────────────────────────────
REFERENCE_STANDARDS, FABRICATED_STANDARDS_PATTERNS, ISO_PREFIXES = load_policy()
