"""
DOCSREG document type registry — loads and validates office document type configs.

Reads ``config/docsreg/office_document_types.yaml`` and returns a list of
:class:`DocumentTypeConfig` instances.  The YAML path is resolved relative to
the repository root (two levels above this file's parent).

Design constraints:
  - Fail-closed: returns ``[]`` on any error; never raises.
  - No hard YAML dependency at import time (lazy ``import yaml``).
  - ``enabled=False`` entries are silently filtered out.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("docsreg_document_type_registry")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OFFICE_DOC_TYPES_CONFIG_PATH: str = "config/docsreg/office_document_types.yaml"

DEFAULT_TARGET_QUALITY: float = 0.98
DEFAULT_MAX_CYCLES: int = 10


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DocumentTypeConfig:
    """Configuration for a single certifiable document type.

    Parameters
    ----------
    id:
        Machine-readable slug used as a task type key.
    name:
        Human-readable display name.
    description:
        One-sentence description of the document type.
    target_quality:
        Minimum quality score required to certify (0.0 – 1.0).
    max_cycles:
        Hard cap on repair cycles before escalation.
    enabled:
        Whether this document type participates in certification campaigns.
    """

    id: str
    name: str
    description: str
    target_quality: float
    max_cycles: int
    enabled: bool


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _default_config_path() -> Path:
    """Return the absolute path to the default YAML config.

    Resolves relative to the repository root (``parents[2]`` from this
    file's location inside ``ops/docsreg/``).
    """
    return Path(__file__).resolve().parents[2] / OFFICE_DOC_TYPES_CONFIG_PATH


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_document_type_registry(
    config_path: str | Path | None = None,
) -> list[DocumentTypeConfig]:
    """Load and return all *enabled* document type configurations.

    Parameters
    ----------
    config_path:
        Override path to the YAML file.  When ``None``, uses
        :func:`_default_config_path`.

    Returns
    -------
    list[DocumentTypeConfig]
        Enabled document types in the order they appear in the YAML.
        Returns ``[]`` on any error (missing file, invalid YAML, missing
        required fields).  Never raises.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        log.error("load_document_type_registry: PyYAML not installed")
        return []

    path = Path(config_path) if config_path is not None else _default_config_path()

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.error("load_document_type_registry: config not found: %s", path)
        return []
    except OSError as exc:
        log.error("load_document_type_registry: cannot read %s: %s", path, exc)
        return []

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        log.error("load_document_type_registry: YAML parse error in %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        log.error(
            "load_document_type_registry: expected top-level mapping in %s, got %s",
            path,
            type(data).__name__,
        )
        return []

    entries = data.get("document_types")
    if not isinstance(entries, list):
        log.error(
            "load_document_type_registry: 'document_types' key missing or not a list in %s",
            path,
        )
        return []

    result: list[DocumentTypeConfig] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            log.warning(
                "load_document_type_registry: skipping non-dict entry at index %d", i
            )
            continue

        # Required fields
        try:
            doc_id: str = str(entry["id"])
            name: str = str(entry["name"])
        except KeyError as exc:
            log.warning(
                "load_document_type_registry: skipping entry %d — missing required field %s",
                i,
                exc,
            )
            continue

        description: str = str(entry.get("description", ""))

        # Optional numeric fields — guard against non-numeric YAML values
        try:
            target_quality = float(
                entry.get("target_quality", DEFAULT_TARGET_QUALITY)
            )
            max_cycles = int(entry.get("max_cycles", DEFAULT_MAX_CYCLES))
        except (ValueError, TypeError) as exc:
            log.warning(
                "load_document_type_registry: skipping entry %d — bad numeric field: %s",
                i,
                exc,
            )
            continue

        # Range validation
        if not (0.0 <= target_quality <= 1.0):
            log.warning(
                "load_document_type_registry: skipping entry %d — "
                "target_quality %.3f is outside [0.0, 1.0]",
                i,
                target_quality,
            )
            continue
        if max_cycles <= 0:
            log.warning(
                "load_document_type_registry: skipping entry %d — "
                "max_cycles %d must be a positive integer",
                i,
                max_cycles,
            )
            continue

        # Handle quoted-string booleans (e.g. enabled: "false")
        raw_enabled = entry.get("enabled", True)
        if isinstance(raw_enabled, bool):
            enabled: bool = raw_enabled
        elif isinstance(raw_enabled, str):
            enabled = raw_enabled.strip().lower() not in ("false", "0", "no", "off")
        else:
            enabled = bool(raw_enabled)

        if not enabled:
            continue

        result.append(
            DocumentTypeConfig(
                id=doc_id,
                name=name,
                description=description,
                target_quality=target_quality,
                max_cycles=max_cycles,
                enabled=enabled,
            )
        )

    log.debug(
        "load_document_type_registry: loaded %d enabled types from %s",
        len(result),
        path,
    )
    return result


def get_enabled_document_type_ids(
    config_path: str | Path | None = None,
) -> list[str]:
    """Return the IDs of all enabled document types.

    Convenience wrapper around :func:`load_document_type_registry`.

    Parameters
    ----------
    config_path:
        Override path to the YAML file; passed through to
        :func:`load_document_type_registry`.

    Returns
    -------
    list[str]
        Ordered list of enabled document type IDs, or ``[]`` on any error.
    """
    return [dt.id for dt in load_document_type_registry(config_path)]
