#!/usr/bin/env python3
"""Produce the single operator outcome for one canonical daily run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def source_metrics(run: dict) -> dict:
    metrics = {
        "source_report_available": False,
        "inbox_discovered": 0,
        "web_discovered": 0,
        "discovery_rejected": 0,
        "deduplicated": 0,
        "passed_discovery_filter": len(run.get("rows", [])),
    }
    raw_path = str(run.get("source_scan") or "").strip()
    if not raw_path:
        return metrics
    path = Path(raw_path)
    if not path.is_file():
        return metrics
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return metrics
    inbox = payload.get("inbox_scan") or {}
    web = payload.get("web_scan") or {}
    metrics.update(
        {
            "source_report_available": True,
            "inbox_discovered": int(inbox.get("total", 0) or 0),
            "web_discovered": int(web.get("total", 0) or 0),
            "discovery_rejected": int(inbox.get("ignored", 0) or 0)
            + int(web.get("ignored", 0) or 0),
            "deduplicated": int(inbox.get("deduplicated", 0) or 0)
            + int(web.get("deduplicated", 0) or 0),
            "passed_discovery_filter": int(
                payload.get("combined_kept_after_cross_dedup", len(run.get("rows", []))) or 0
            ),
        }
    )
    return metrics


def operator_status(run: dict, metrics: dict) -> str:
    status = str(run.get("run_status", run.get("status", "PASS")) or "PASS")
    if status != "PASS":
        return status
    if run.get("rows"):
        return "PASS"
    discovered = metrics["inbox_discovered"] + metrics["web_discovered"]
    return "NO_MATCHES_AFTER_FILTER" if discovered else "NO_INPUT"


def fallback_rows(run: dict, employer_registry: Path | None = None) -> list[dict]:
    from job_filter_bot import _canonical_url, _is_direct_vacancy_url

    registry = {}
    if employer_registry and employer_registry.exists():
        try:
            registry = {str(r.get("company", "")).casefold(): r for r in json.loads(employer_registry.read_text()).get("records", [])}
        except Exception:
            registry = {}
    out, seen_urls, seen_positions = [], set(), set()
    for row in run.get("rows", []):
        if row.get("status") in {
            "draft_created",
            "existing_gmail_application",
            "duplicate_blocked",
            "rejected_ineligible",
        }:
            continue
        source_url = str(row.get("source_url", ""))
        if not _is_direct_vacancy_url(source_url):
            continue
        canonical_url = _canonical_url(source_url)
        company_key = str(row.get("company", "")).strip().casefold()
        title_key = str(row.get("title", "")).strip().casefold()
        location_key = str(row.get("location", "")).strip().casefold()
        position_key = (company_key, title_key, location_key)
        if canonical_url in seen_urls or (company_key and position_key in seen_positions):
            continue
        seen_urls.add(canonical_url)
        if company_key:
            seen_positions.add(position_key)
        employer = registry.get(company_key, {})
        out.append({
            "company": row.get("company", ""),
            "official_site": employer.get("official_site", employer.get("website", "")),
            "careers_url": employer.get("career_site", employer.get("careers_url", "")),
            "vacancy_title": row.get("title", ""),
            "location": row.get("location", ""),
            "region": row.get("region", ""),
            "vacancy_url": canonical_url,
            "reason": row.get("status", "NO_VERIFIED_DRAFT"),
            "contact_route": employer.get("contact_route", employer.get("career_site", "")),
            "recruiter_link": row.get("recruiter_url", ""),
        })
    return out


def format_message(run: dict, fallback: list[dict]) -> str:
    metrics = source_metrics(run)
    status = operator_status(run, metrics)
    marker = "✅" if status == "PASS" else ("⚠️" if status in {"NO_INPUT", "NO_MATCHES_AFTER_FILTER"} else "❌")
    lines = [
        "🌏 JOB FILTER DAILY",
        "",
        f"{marker} Status: {status}",
        f"Vacancies discovered: {metrics['inbox_discovered'] + metrics['web_discovered']}",
        f"  Gmail inbox: {metrics['inbox_discovered']}",
        f"  Job sites: {metrics['web_discovered']}",
        f"Rejected at discovery filter: {metrics['discovery_rejected']}",
        f"Duplicates removed: {metrics['deduplicated']}",
        f"Passed discovery filter: {metrics['passed_discovery_filter']}",
        f"Vacancies evaluated for draft: {len(run.get('rows', []))}",
        f"Rejected by eligibility: {run.get('rejected_ineligible', 0)}",
        f"Gmail Drafts created: {run.get('drafts_created', 0)}",
    ]
    if fallback:
        visible = fallback[:3]
        lines += ["", f"MANUAL FALLBACK: {len(fallback)} (showing {len(visible)})"]
        for item in visible:
            url = str(item["vacancy_url"])
            if len(url) > 180:
                url = f"{url[:177]}..."
            lines += [f"{item['company']} — {item['vacancy_title']}", url, f"Reason: {item['reason']}"]
        if len(fallback) > len(visible):
            lines.append(f"Remaining {len(fallback) - len(visible)} are recorded in the daily outcome JSON.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("draft_run", type=Path); ap.add_argument("--employer-registry", type=Path); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args(); run = json.loads(args.draft_run.read_text(encoding="utf-8")); fallback = fallback_rows(run, args.employer_registry)
    metrics = source_metrics(run)
    status = operator_status(run, metrics)
    result = {"status": status, "source_metrics": metrics, "telegram_message_count": 1, "drafts_created": run.get("drafts_created", 0), "fallback_count": len(fallback), "fallback": fallback, "telegram_message": format_message(run, fallback), "sent": False}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_send:
        from job_outreach.telegram_notifier import TelegramNotifier
        delivery = TelegramNotifier().deliver(result["telegram_message"], related_run=str(run.get("source_scan", "")))
        result["sent"] = delivery.get("status") == "delivered"; result["delivery"] = delivery
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if status not in {"PASS", "NO_INPUT", "NO_MATCHES_AFTER_FILTER"}:
        return 2
    return 0 if args.no_send or result.get("sent") else 3


if __name__ == "__main__": raise SystemExit(main())
