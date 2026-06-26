from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ops.docsreg.standards_registry import list_registered_standard_records
from ops.docgen.standards import official_standard_metadata


def _base_id(value: str) -> str:
    return re.sub(r":\d{4}(?:-[A-Z0-9]+)?$", "", value.strip(), flags=re.I)


def _year(value: str) -> str:
    match = re.search(r":(\d{4})(?:-[A-Z0-9]+)?$", value.strip(), flags=re.I)
    return match.group(1) if match else ""


def _metadata_index() -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for record in list_registered_standard_records():
        index.setdefault(_base_id(str(record.get("standard_id") or "")), []).append(record)
    return index


def _registered_source_path(record: dict[str, Any]) -> str:
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("source_path", "file_path", "path"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    return str(record.get("source") or "").strip()


def _registered_candidate(
    standard_id: str,
    metadata_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candidates = metadata_index.get(_base_id(standard_id), [])
    exact = next(
        (
            record for record in candidates
            if str(record.get("standard_id") or "") == standard_id
        ),
        None,
    )
    titled = exact or next(
        (record for record in candidates if str(record.get("title") or "").strip()),
        None,
    )
    return dict(titled or {})


def _registered_source_fields(record: dict[str, Any]) -> dict[str, Any]:
    source_path = _registered_source_path(record)
    return {
        "registered_source_path": source_path,
        "registered_source_exists": bool(source_path and Path(source_path).exists()),
        "registered_source_status": str(record.get("status") or ""),
        "registered_source_domain": str(record.get("domain") or ""),
    }


def _mentioned_registered_records(
    request_text: str,
    metadata_index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    lower = request_text.casefold()
    matches: list[dict[str, Any]] = []
    for records in metadata_index.values():
        for record in records:
            standard_id = str(record.get("standard_id") or "").strip()
            title = str(record.get("title") or "").strip()
            needles = [standard_id.casefold(), title.casefold()]
            if any(len(needle) >= 4 and needle in lower for needle in needles):
                matches.append(dict(record))
                break
    return matches


def _standard_record(
    standard_id: str,
    *,
    use: str,
    metadata_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    official = official_standard_metadata(standard_id)
    registered = _registered_candidate(standard_id, metadata_index)
    if official:
        reference_code = str(
            official.get("content_basis_code")
            or official.get("current_code")
            or standard_id
        )
        reference_year = str(
            official.get("content_basis_year")
            or official.get("publication_year")
            or ""
        )
        current_code = str(official.get("current_code") or standard_id)
        return {
            "standard_id": current_code,
            "requested_standard_id": standard_id,
            "code": reference_code,
            "title": str(
                official.get("content_basis_title")
                or official.get("title")
                or ""
            ),
            "publication_year": reference_year,
            "edition_verified": bool(reference_year),
            "metadata_source": str(official.get("metadata_source") or ""),
            "official_url": str(official.get("official_url") or ""),
            "use": use,
            "currentness_status": str(
                official.get("content_basis_status")
                or official.get("status")
                or "OFFICIAL_METADATA"
            ),
            "metadata_only": official.get("content_available") == "metadata_only",
            "clause_content_authorized": False,
            "metadata_verified_at": official.get("metadata_verified_at"),
            "current_official_code": current_code,
            "current_official_title": str(official.get("title") or ""),
            "current_official_publication_year": str(
                official.get("publication_year") or ""
            ),
            "current_official_publication_date": str(
                official.get("publication_date") or ""
            ),
            "under_review_against_current_edition": reference_code != current_code,
            **_registered_source_fields(registered),
        }
    candidates = metadata_index.get(_base_id(standard_id), [])
    exact = next(
        (
            record for record in candidates
            if str(record.get("standard_id") or "") == standard_id
            and str(record.get("title") or "").strip()
        ),
        None,
    )
    titled = exact or next(
        (record for record in candidates if str(record.get("title") or "").strip()),
        {},
    )
    publication_year = _year(standard_id)
    return {
        "standard_id": standard_id,
        "code": standard_id,
        "title": str(titled.get("title") or "").strip(),
        "publication_year": publication_year,
        "edition_verified": bool(publication_year and exact),
        "metadata_source": str(titled.get("source") or ""),
        "official_url": str(titled.get("official_url") or ""),
        "use": use,
        "currentness_status": (
            "REGISTERED_EDITION"
            if publication_year and exact
            else "SOURCE_SITE_CONFIRMATION_REQUIRED"
        ),
        **_registered_source_fields(dict(titled or {})),
    }


def bind_standards(request: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    standards = []
    seen: set[str] = set()
    metadata_index = _metadata_index()
    for item in sources.get("standards") or []:
        standard_id = str(item.get("standard_id") if isinstance(item, dict) else item).strip()
        if standard_id and standard_id not in seen:
            seen.add(standard_id)
            standards.append(
                _standard_record(
                    standard_id,
                    use="formation_or_discovery",
                    metadata_index=metadata_index,
                )
            )
    text = " ".join([str(request.get("request") or ""), str(request.get("title") or "")]).lower()
    if "iso 55001" in text and "ISO 55001" not in seen:
        standards.append(
            _standard_record(
                "ISO 55001",
                use="domain_requirement",
                metadata_index=metadata_index,
            )
        )
    if "iso 55002" in text and "ISO 55002" not in seen:
        standards.append(
            _standard_record(
                "ISO 55002",
                use="domain_guidance",
                metadata_index=metadata_index,
            )
        )
    for record in _mentioned_registered_records(text, metadata_index):
        standard_id = str(record.get("standard_id") or "").strip()
        if standard_id and standard_id not in seen:
            seen.add(standard_id)
            standards.append(
                _standard_record(
                    standard_id,
                    use="registered_request_match",
                    metadata_index=metadata_index,
                )
            )
    return {
        "status": "PASS",
        "selected_standards": standards,
        "reference_register_ready": all(
            item.get("code") and item.get("title") for item in standards
        ),
        "edition_verification_required": [
            item["standard_id"]
            for item in standards
            if not item.get("edition_verified")
        ],
        "blockers": [],
    }
