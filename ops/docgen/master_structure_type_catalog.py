"""Authoritative MST catalog and safe baseline resolver.

The existing ``STRUCTURE_SUPPLY_REGISTRY`` remains the registry of record for
runtime supply.  This module adds catalog metadata and technical empty
baselines without changing the canonical DOCGEN manifest or populated masters.
Empty baselines are resolvable for audit/smoke purposes only and are never
generation-ready.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SUPPLY_REGISTRY_PATH = ROOT / "aims_workspace/program_state/STRUCTURE_SUPPLY_REGISTRY.json"
BASELINE_ROOT = ROOT / "aims_workspace/docgen/master_structures/baselines"
CATALOG_JSON = ROOT / "aims_workspace/docgen/master_structures/MASTER_STRUCTURE_TYPE_CATALOG.json"
CATALOG_MD = ROOT / "aims_workspace/docgen/master_structures/MASTER_STRUCTURE_TYPE_CATALOG.md"

_RAW = (
    ("MST-001", "technical_system_philosophy", "Technical System Philosophy", "philosophy", ("technical_system", "facility_subsystem")),
    ("MST-002", "functional_management_philosophy", "Functional / Management Philosophy", "philosophy", ("business_function", "management_system")),
    ("MST-003", "policy", "Policy", "policy", ("enterprise", "business_function", "management_system")),
    ("MST-004", "asset_technical_system_strategy", "Asset / Technical System Strategy", "strategy", ("asset", "technical_system", "facility")),
    ("MST-005", "corporate_functional_strategy", "Corporate / Functional Strategy", "strategy", ("enterprise", "business_function", "asset_portfolio")),
    ("MST-006", "framework", "Framework", "framework", ("enterprise", "business_function", "management_system")),
    ("MST-007", "charter_mandate", "Charter / Mandate", "charter", ("enterprise", "business_function", "project", "programme")),
    ("MST-008", "governance_model", "Governance Model", "governance", ("enterprise", "business_function", "management_system")),
    ("MST-009", "operating_model", "Operating Model", "operating_model", ("enterprise", "business_function", "facility")),
    ("MST-010", "equipment_manual", "Equipment Manual", "manual", ("single_equipment_item", "equipment_package")),
    ("MST-011", "technical_system_manual", "Technical System Manual", "manual", ("technical_system", "facility_subsystem")),
    ("MST-012", "management_system_manual", "Management System Manual", "manual", ("management_system", "enterprise")),
    ("MST-013", "technical_standard", "Technical Standard", "standard", ("equipment_class", "technical_system", "engineering")),
    ("MST-014", "management_process_standard", "Management / Process Standard", "standard", ("business_function", "management_system")),
    ("MST-015", "equipment_specification", "Equipment Specification", "specification", ("single_equipment_item", "equipment_class")),
    ("MST-016", "technical_system_specification", "Technical System Specification", "specification", ("technical_system", "facility_subsystem")),
    ("MST-017", "service_work_specification", "Service / Work Specification", "specification", ("service", "work_package", "business_function")),
    ("MST-018", "design_basis", "Design Basis", "design", ("technical_system", "process_unit", "facility", "project")),
    ("MST-019", "equipment_package_datasheet", "Equipment / Package Datasheet", "datasheet", ("single_equipment_item", "equipment_package")),
    ("MST-020", "asset_equipment_plan", "Asset / Equipment Plan", "plan", ("asset", "single_equipment_item", "equipment_class")),
    ("MST-021", "system_facility_plan", "System / Facility Plan", "plan", ("technical_system", "facility")),
    ("MST-022", "programme_functional_plan", "Programme / Functional Plan", "plan", ("business_function", "project", "programme")),
    ("MST-023", "equipment_procedure", "Equipment Procedure", "procedure", ("single_equipment_item", "equipment_package")),
    ("MST-024", "technical_system_procedure", "Technical System Procedure", "procedure", ("technical_system", "facility_subsystem")),
    ("MST-025", "business_process_procedure", "Business Process Procedure", "procedure", ("business_function", "management_system")),
    ("MST-026", "physical_task_work_instruction", "Physical Task Work Instruction", "work_instruction", ("single_equipment_item", "work_package")),
    ("MST-027", "administrative_process_work_instruction", "Administrative / Process Work Instruction", "work_instruction", ("business_function", "management_system")),
    ("MST-028", "equipment_system_instruction", "Equipment / System Instruction", "instruction", ("single_equipment_item", "technical_system")),
    ("MST-029", "administrative_process_instruction", "Administrative / Process Instruction", "instruction", ("business_function", "management_system")),
    ("MST-030", "technical_guide", "Technical Guide", "guide", ("single_equipment_item", "technical_system", "equipment_class")),
    ("MST-031", "management_process_guideline", "Management / Process Guideline", "guideline", ("business_function", "management_system")),
    ("MST-032", "methodology", "Methodology", "methodology", ("business_function", "technical_system", "enterprise")),
    ("MST-033", "technical_task_risk_assessment", "Technical / Task Risk Assessment", "risk_assessment", ("single_equipment_item", "technical_system", "work_package")),
    ("MST-034", "enterprise_business_risk_assessment", "Enterprise / Business Risk Assessment", "risk_assessment", ("enterprise", "business_function", "programme")),
    ("MST-035", "audit_report", "Audit Report", "audit_report", ("business_function", "management_system", "technical_system")),
    ("MST-036", "regulation", "Regulation", "regulation", ("enterprise", "business_function", "technical_system", "facility")),
    ("MST-037", "job_description", "Job Description", "job_description", ("enterprise", "business_function")),
    # Phase 2: MSDG recovery — 12 new master types to support blocked documents (MST-038..MST-049)
    ("MST-038", "strategy", "Strategy", "strategy", ("enterprise", "business_function", "asset", "technical_system")),
    ("MST-039", "plan", "Plan", "plan", ("enterprise", "business_function", "asset", "technical_system", "facility")),
    ("MST-040", "test_verification_report", "Test / Verification Report", "report", ("technical_system", "work_package", "project")),
    ("MST-041", "performance_report", "Performance Report", "report", ("asset", "technical_system", "business_function")),
    ("MST-042", "progress_status_report", "Progress / Status Report", "report", ("project", "programme", "business_function")),
    ("MST-043", "technical_asset_system_assessment_report", "Technical / Asset / System Assessment Report", "report", ("asset", "technical_system", "facility")),
    ("MST-044", "change_request", "Change Request", "change_request", ("enterprise", "business_function", "technical_system", "project")),
    ("MST-045", "approval_signoff_record", "Approval / Sign-Off Record", "approval_record", ("enterprise", "business_function", "project", "management_system")),
    ("MST-046", "asset_system_register", "Asset / System Register", "register", ("asset", "technical_system", "facility", "equipment_class")),
    ("MST-047", "checklist", "Checklist", "checklist", ("work_package", "business_function", "technical_system")),
    ("MST-048", "material_service_request", "Material / Service Request", "request", ("business_function", "work_package")),
    ("MST-049", "meeting_minutes_decision_record", "Meeting Minutes / Decision Record", "record", ("enterprise", "business_function", "project", "programme")),
)

_FORBIDDEN_CONTEXT = (
    "discipline", "business_function", "lifecycle_context", "equipment_class",
    "project_phase", "company_name", "facility_name",
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog_entries() -> list[dict[str, Any]]:
    entries = [
        {
            "catalog_id": catalog_id,
            "master_type_id": type_id,
            "display_name": display_name,
            "structure_class": structure_class,
            "application_levels_allowed": list(levels),
            "application_levels_prohibited": [],
            "parent_type": None,
            "aliases": [],
            "positive_classification_signals": [],
            "negative_classification_signals": [],
            "context_metadata_fields": [
                "application_level", "business_function", "discipline",
                "equipment_or_system_class", "lifecycle_context",
            ],
            "non_type_context_values": list(_FORBIDDEN_CONTEXT),
            "baseline_master_ref": None,
            "active_master_version": None,
            "master_hash": None,
            "source_document_count": 0,
            "required_contract_count": 0,
            "supplemental_contract_count": 0,
            "accumulated_source_meaning_count": 0,
            "docgen_binding_status": "REGISTERED_NOT_READY",
            "msdg_enrichment_status": "AWAITING_SOURCE_DOCUMENT",
            "production_readiness": "NOT_READY",
            "known_gaps": ["No source-backed meanings admitted; structure intentionally empty."],
            "created_from_source": False,
        }
        for catalog_id, type_id, display_name, structure_class, levels in _RAW
    ]
    job_description = next(
        entry for entry in entries if entry["master_type_id"] == "job_description"
    )
    job_description["aliases"] = [
        "job description",
        "position description",
        "role description",
        "должностная инструкция",
        "должностн",
        "описание должности",
    ]
    job_description["positive_classification_signals"] = list(
        job_description["aliases"]
    )
    job_description["negative_classification_signals"] = [
        "job advertisement",
        "vacancy announcement",
        "resume",
        "curriculum vitae",
    ]
    return entries


def load_supply_registry(path: Path = SUPPLY_REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_catalog(entries: list[dict[str, Any]] | None = None) -> list[str]:
    entries = entries or catalog_entries()
    errors: list[str] = []
    ids = [x.get("master_type_id") for x in entries]
    catalog_ids = [x.get("catalog_id") for x in entries]
    if len(entries) != len(_RAW):
        errors.append(f"expected {len(_RAW)} catalog entries, got {len(entries)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate master_type_id")
    if len(catalog_ids) != len(set(catalog_ids)):
        errors.append("duplicate catalog_id")
    for entry in entries:
        if not entry.get("master_type_id") or not entry.get("catalog_id"):
            errors.append("missing type or catalog id")
        if entry.get("production_readiness") == "PRODUCTION_READY":
            errors.append(f"empty catalog type marked production-ready: {entry['master_type_id']}")
    return errors


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp = Path(handle.name)
    os.replace(tmp, path)


def register_catalog(*, registry_path: Path = SUPPLY_REGISTRY_PATH, baseline_root: Path = BASELINE_ROOT) -> dict[str, Any]:
    entries = catalog_entries()
    errors = validate_catalog(entries)
    if errors:
        raise ValueError("invalid MST catalog: " + "; ".join(errors))
    registry = load_supply_registry(registry_path)
    existing_snapshot: dict[str, dict[str, Any]] = {}
    for key, value in registry.get("entries", {}).items():
        path = ROOT / str(value.get("path", ""))
        existing_snapshot[key] = {"sha256": sha256_path(path) if path.is_file() else value.get("sha256"), "version": value.get("version"), "status": value.get("status")}
    registered: list[dict[str, Any]] = []
    for catalog in entries:
        type_id = catalog["master_type_id"]
        registry_id = f"mst.{type_id}"
        path = baseline_root / f"{type_id}.json"
        baseline = {
            "canonical_id": registry_id,
            "master_type_id": type_id,
            "catalog_id": catalog["catalog_id"],
            "display_name": catalog["display_name"],
            "schema_version": "1.0",
            "version": "0.0.0",
            "status": "BASELINE_EMPTY",
            "approved": False,
            "production_active": False,
            "activation_blocked": True,
            "generation_sections": [],
            "section_contracts": [],
            "supplemental_question_contracts": [],
            "source_meaning_lineage": [],
            "overlay_bindings": [],
            "created_from_source": False,
            "creation_reason": "CATALOG_REGISTRATION_ONLY",
            "docgen_generation_blocked": True,
        }
        _atomic_json(path, baseline)
        digest = sha256_path(path)
        catalog["baseline_master_ref"] = registry_id
        catalog["master_hash"] = digest
        catalog["baseline_path"] = str(path.relative_to(ROOT))
        registry.setdefault("entries", {})[registry_id] = {
            **catalog,
            "document_type": type_id,
            "family": catalog["structure_class"],
            "canonical_id": registry_id,
            "path": str(path.relative_to(ROOT)),
            "sha256": digest,
            "version": "0.0.0",
            "owner_line": "master_type_catalog",
            "status": "BASELINE_EMPTY",
            "pipeline_binding": {
                "enabled": False,
                "auto_select_by_context": False,
                "generation_model": None,
                "last_generation_run": None,
                "last_generation_quality": None,
                "empty_baseline_generation_blocked": True,
            },
        }
        registered.append({"registry_id": registry_id, "master_type_id": type_id, "path": str(path.relative_to(ROOT)), "sha256": digest})
    registry["registry_version"] = "1.1.0"
    registry["catalog_schema"] = "aims.msdg.master_structure_type_catalog.v1"
    registry["catalog_entry_count"] = len(entries)
    registry["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(registry_path, registry)
    return {"entries": entries, "registered": registered, "existing_snapshot": existing_snapshot, "registry_path": str(registry_path.relative_to(ROOT))}


def resolve_registered_master_type(master_type_id: str, *, registry_path: Path = SUPPLY_REGISTRY_PATH) -> dict[str, Any]:
    registry = load_supply_registry(registry_path)
    type_id = str(master_type_id).strip()
    catalog = next((x for x in catalog_entries() if x["master_type_id"] == type_id), None)
    if catalog is None:
        raise ValueError(f"unknown master type: {type_id}")
    entry = registry.get("entries", {}).get(f"mst.{type_id}")
    if not entry:
        raise ValueError(f"master type is not registered: {type_id}")
    path = ROOT / entry["path"]
    if not path.is_file() or sha256_path(path) != entry["sha256"]:
        raise ValueError(f"registered master checksum mismatch: {type_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"catalog": catalog, "registry_entry": entry, "baseline": data, "generation_blocked": data.get("docgen_generation_blocked") is True}


def render_catalog_markdown(entries: list[dict[str, Any]] | None = None) -> str:
    entries = entries or catalog_entries()
    lines = ["# Master Structure Type Catalog", "", f"Authoritative catalog: MST-001..MST-{len(entries):03d}. Empty baselines are catalog-registration artifacts only.", "", "| Catalog ID | Master Type ID | Display Name | Class | Baseline Status | DOCGEN |", "|---|---|---|---|---|---|"]
    lines += [f"| {x['catalog_id']} | `{x['master_type_id']}` | {x['display_name']} | {x['structure_class']} | `BASELINE_EMPTY` | `REGISTERED_NOT_READY` |" for x in entries]
    return "\n".join(lines) + "\n"
