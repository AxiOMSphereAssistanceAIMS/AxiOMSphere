from __future__ import annotations

def validate_package(pkg: dict) -> list[str]:
    req = {
        "hermes_skill_package_id","source_author","incubated_by","source_repair_case_id",
        "source_hermes_review_id","target_agent_id","skill_name","allowed_actions",
        "forbidden_actions","maturity_status",
    }
    errs = []
    missing = req - set(pkg)
    if missing:
        errs.append("missing:" + ",".join(sorted(missing)))
    if pkg.get("source_author") != "hermes":
        errs.append("source_author_not_hermes")
    if pkg.get("incubated_by") != "hermes":
        errs.append("incubated_by_not_hermes")
    if pkg.get("target_agent_id") not in {"repairman", "mainy_repairman"}:
        errs.append("target_agent_invalid")
    return errs
