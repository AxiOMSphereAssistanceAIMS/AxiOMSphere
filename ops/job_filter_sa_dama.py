from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

from job_filter import JobFilterConfig


SA_DAMA_CODES = ("233512", "233513")

SA_DAMA_COMPANIES = (
    "Santos",
    "BHP",
    "SA Water",
    "Beach Energy",
    "ASC",
    "Worley",
    "KBR",
    "Jacobs",
    "GHD",
    "AECOM",
    "Ventia",
    "Downer",
    "UGL",
    "Exact Mining Services",
    "Epic Projects and Consulting",
    "TMK Consulting Engineers",
    "Tonkin",
)

SA_DAMA_ROLES = (
    "Operations Readiness Manager",
    "Operations Readiness Lead",
    "Asset Integrity Manager",
    "Maintenance Manager",
    "Reliability Manager",
    "Operations Excellence Manager",
    "Senior Maintenance Engineer",
    "Lead Maintenance Engineer",
    "Lead Reliability Engineer",
    "Maintenance Superintendent",
    "Brownfield Project Manager",
    "Start-up Manager",
)

DAMA_REGION_CONFIG: tuple[dict[str, Any], ...] = (
    {
        "name": "Adelaide City Technology and Innovation Advancement",
        "state": "SA",
        "priority": 1,
        "weight": 1.0,
        "search_locations": ("Adelaide SA", "Adelaide South Australia"),
        "match_terms": ("adelaide", "adelaide sa"),
    },
    {
        "name": "South Australia Regional",
        "state": "SA",
        "priority": 1,
        "weight": 1.0,
        "search_locations": (
            "South Australia",
            "Whyalla SA",
            "Olympic Dam SA",
            "Roxby Downs SA",
            "Port Augusta SA",
            "Cooper Basin SA",
            "Mount Gambier SA",
            "Port Pirie SA",
        ),
        "match_terms": (
            "south australia",
            "whyalla",
            "olympic dam",
            "roxby downs",
            "port augusta",
            "cooper basin",
            "mount gambier",
            "port pirie",
        ),
    },
    {
        "name": "Northern Territory DAMA",
        "state": "NT",
        "priority": 1,
        "weight": 1.0,
        "search_locations": ("Northern Territory", "Darwin NT", "Palmerston NT", "Alice Springs NT", "Katherine NT"),
        "match_terms": ("northern territory", "darwin", "palmerston", "alice springs", "katherine", " nt"),
    },
    {
        "name": "Western Australia State DAMA",
        "state": "WA",
        "priority": 1,
        "weight": 1.0,
        "search_locations": ("Western Australia", "Perth WA", "Regional WA"),
        "match_terms": ("western australia", "perth", "regional wa"),
    },
    {
        "name": "Pilbara",
        "state": "WA",
        "priority": 1,
        "weight": 1.0,
        "search_locations": ("Pilbara WA", "Karratha WA", "Port Hedland WA", "Newman WA", "Tom Price WA"),
        "match_terms": ("pilbara", "karratha", "port hedland", "newman", "tom price"),
    },
    {
        "name": "Goldfields",
        "state": "WA",
        "priority": 2,
        "weight": 0.8,
        "search_locations": ("Kalgoorlie WA", "Kalgoorlie-Boulder WA", "Goldfields WA"),
        "match_terms": ("kalgoorlie", "kalgoorlie-boulder", "goldfields"),
    },
    {
        "name": "East Kimberley",
        "state": "WA",
        "priority": 2,
        "weight": 0.8,
        "search_locations": ("East Kimberley WA", "Kununurra WA", "Wyndham WA"),
        "match_terms": ("east kimberley", "kununurra", "wyndham"),
    },
    {
        "name": "South West",
        "state": "WA",
        "priority": 2,
        "weight": 0.8,
        "search_locations": ("South West WA", "Bunbury WA", "Busselton WA", "Collie WA"),
        "match_terms": ("south west wa", "bunbury", "busselton", "collie"),
    },
    {
        "name": "Far North Queensland",
        "state": "QLD",
        "priority": 2,
        "weight": 0.8,
        "search_locations": ("Cairns QLD", "Far North Queensland", "Cairns Region QLD"),
        "match_terms": ("cairns", "far north queensland", "cairns region", "fnq"),
    },
    {
        "name": "Townsville",
        "state": "QLD",
        "priority": 2,
        "weight": 0.8,
        "search_locations": ("Townsville QLD",),
        "match_terms": ("townsville",),
    },
    {
        "name": "Orana",
        "state": "NSW",
        "priority": 3,
        "weight": 0.6,
        "search_locations": ("Orana NSW", "Dubbo NSW", "Mudgee NSW", "Cobar NSW"),
        "match_terms": ("orana", "dubbo", "mudgee", "cobar"),
    },
    {
        "name": "Goulburn Valley",
        "state": "VIC",
        "priority": 3,
        "weight": 0.6,
        "search_locations": ("Goulburn Valley VIC", "Shepparton VIC", "Echuca VIC", "Kyabram VIC"),
        "match_terms": ("goulburn valley", "shepparton", "echuca", "kyabram"),
    },
    {
        "name": "Great South Coast",
        "state": "VIC",
        "priority": 3,
        "weight": 0.6,
        "search_locations": ("Great South Coast VIC", "Warrnambool VIC", "Portland VIC", "Hamilton VIC"),
        "match_terms": ("great south coast", "warrnambool", "portland vic", "hamilton vic"),
    },
)

SA_DAMA_VISA_QUERIES = (
    "DAMA",
    "South Australia DAMA",
    "Designated Area Migration Agreement",
    "482 visa",
    "186 visa",
    "494 visa",
    "employer sponsored visa",
    "visa sponsorship",
    "Skills in Demand visa",
)

SA_DAMA_COMPANY_OUTREACH = {
    "santos": {
        "website": "https://www.santos.com/",
        "careers": "https://www.santos.com/careers/",
        "linkedin": "https://www.linkedin.com/company/santos-ltd/",
        "contact_hint": "Talent Acquisition / Asset Integrity / Maintenance leadership",
    },
    "bhp": {
        "website": "https://www.bhp.com/",
        "careers": "https://www.bhp.com/careers",
        "linkedin": "https://au.linkedin.com/company/bhp",
        "contact_hint": "Talent Acquisition / Olympic Dam maintenance or reliability leadership",
    },
    "sa water": {
        "website": "https://www.sawater.com.au/",
        "careers": "https://careers.sawater.com.au/jobs/search",
        "linkedin": "https://au.linkedin.com/company/sa-water",
        "contact_hint": "Talent Acquisition / Asset Management / Operations & Maintenance leadership",
    },
    "beach energy": {
        "website": "https://beachenergy.com.au/",
        "careers": "https://beachenergy.com.au/work-at-beach-energy/",
        "linkedin": "https://au.linkedin.com/company/beach-energy-ltd",
        "contact_hint": "Talent Acquisition / Cooper Basin operations or maintenance leadership",
    },
    "asc": {
        "website": "https://www.asc.com.au/",
        "careers": "https://www.asc.com.au/careers/",
        "linkedin": "https://au.linkedin.com/company/asc-pty-ltd",
        "contact_hint": "Talent Acquisition / Engineering or sustainment leadership",
    },
    "worley": {
        "website": "https://www.worley.com/",
        "careers": "https://www.worley.com/careers",
        "linkedin": "https://www.linkedin.com/company/worley/",
        "contact_hint": "Talent Acquisition / Maintenance or asset integrity leadership",
    },
    "kbr": {
        "website": "https://www.kbr.com/",
        "careers": "https://www.kbr.com/en/careers",
        "linkedin": "https://www.linkedin.com/company/kbr-inc/",
        "contact_hint": "Talent Acquisition / Defence or infrastructure engineering leadership",
    },
    "jacobs": {
        "website": "https://www.jacobs.com/",
        "careers": "https://careers.jacobs.com/",
        "linkedin": "https://www.linkedin.com/company/jacobs/",
        "contact_hint": "Talent Acquisition / Maintenance or reliability leadership",
    },
    "ghd": {
        "website": "https://www.ghd.com/",
        "careers": "https://www.ghd.com/en/careers",
        "linkedin": "https://www.linkedin.com/company/ghd/",
        "contact_hint": "Talent Acquisition / Asset management or infrastructure leadership",
    },
    "aecom": {
        "website": "https://aecom.com/",
        "careers": "https://aecom.jobs/",
        "linkedin": "https://www.linkedin.com/company/aecom/",
        "contact_hint": "Talent Acquisition / Maintenance or asset integrity leadership",
    },
    "ventia": {
        "website": "https://www.ventia.com/",
        "careers": "https://www.ventia.com/careers",
        "linkedin": "https://www.linkedin.com/company/ventia-pty-ltd/",
        "contact_hint": "Talent Acquisition / Asset maintenance leadership",
    },
    "downer": {
        "website": "https://www.downergroup.com/",
        "careers": "https://www.downergroup.com/careers",
        "linkedin": "https://www.linkedin.com/company/downer/",
        "contact_hint": "Talent Acquisition / Maintenance or project delivery leadership",
    },
    "ugl": {
        "website": "https://www.ugllimited.com/",
        "careers": "https://www.ugllimited.com/careers",
        "linkedin": "https://www.linkedin.com/company/ugl-limited/",
        "contact_hint": "Talent Acquisition / Engineering or maintenance leadership",
    },
    "exact mining services": {
        "website": "https://www.exactmining.com.au/",
        "careers": "https://www.exactmining.com.au/careers/",
        "linkedin": "https://www.linkedin.com/company/exact-mining-services/",
        "contact_hint": "Talent Acquisition / Maintenance Superintendent / Operations Manager",
    },
    "epic projects and consulting": {
        "website": "https://epicprojects.com.au/",
        "careers": "https://epicprojects.com.au/",
        "linkedin": "https://www.linkedin.com/company/epic-projects-and-consulting/",
        "contact_hint": "Talent Acquisition / Maintenance or project delivery leadership",
    },
    "tmk consulting engineers": {
        "website": "https://www.tmkeng.com.au/",
        "careers": "https://www.tmkeng.com.au/",
        "linkedin": "https://www.linkedin.com/company/tmk-consulting-engineers/",
        "contact_hint": "Talent Acquisition / Maintenance or asset integrity leadership",
    },
    "tonkin": {
        "website": "https://www.tonkin.com.au/",
        "careers": "https://www.tonkin.com.au/careers/",
        "linkedin": "https://www.linkedin.com/company/tonkin-consulting/",
        "contact_hint": "Talent Acquisition / Maintenance or reliability leadership",
    },
}


def _split_env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _company_key(company: str) -> str:
    value = (company or "").strip().lower()
    value = value.replace("pty ltd", "").replace("limited", "").replace("ltd", "")
    value = " ".join(value.split())
    return value


def _linkedin_people_search(company: str, title: str = "") -> str:
    query = " ".join(
        part
        for part in (
            company,
            title,
            "talent acquisition OR hiring manager OR maintenance manager OR engineering manager",
        )
        if part
    )
    return "https://www.linkedin.com/search/results/people/?" + urllib.parse.urlencode({"keywords": query})


def enrich_sa_dama_outreach(job: dict) -> dict:
    record = dict(job)
    company = str(record.get("company", "") or "").strip()
    title = str(record.get("title", "") or "").strip()
    key = _company_key(company)

    metadata = SA_DAMA_COMPANY_OUTREACH.get(key)
    if metadata is None and key:
        for candidate_key, candidate_metadata in SA_DAMA_COMPANY_OUTREACH.items():
            if candidate_key and (candidate_key in key or key in candidate_key):
                metadata = candidate_metadata
                break

    if metadata:
        record.setdefault("company_website", metadata.get("website", ""))
        record.setdefault("company_careers_url", metadata.get("careers", ""))
        record.setdefault("company_linkedin_url", metadata.get("linkedin", ""))
        record.setdefault("contact_hint", metadata.get("contact_hint", "Talent Acquisition / Hiring Manager"))
    elif company:
        record.setdefault("contact_hint", "Talent Acquisition / Hiring Manager")

    if company:
        record.setdefault("contact_linkedin_search_url", _linkedin_people_search(company, title))

    return record


def sa_dama_enabled() -> bool:
    raw = os.environ.get("JOB_FILTER_SA_DAMA_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def sa_dama_queries() -> list[str]:
    env_queries = _split_env_list("JOB_FILTER_SA_DAMA_QUERIES")
    if env_queries:
        return _unique(env_queries)
    query_mode = os.environ.get("JOB_FILTER_SA_DAMA_QUERY_MODE", "").strip().lower()
    if query_mode == "roles_only":
        return _unique(list(SA_DAMA_ROLES))

    # Keep the branch focused: role searches find live vacancies; selected company
    # searches catch direct career posts that omit exact role phrases in snippets.
    company_terms = [
        f"{company} {role}"
        for company in SA_DAMA_COMPANIES[:8]
        for role in ("maintenance manager", "asset integrity", "reliability manager", "operations readiness")
    ]
    return _unique([*SA_DAMA_ROLES, *company_terms])


def sa_dama_locations() -> list[str]:
    configured = _split_env_list("JOB_FILTER_SA_DAMA_LOCATIONS")
    if configured:
        return _unique(configured)
    locations: list[str] = []
    for region in DAMA_REGION_CONFIG:
        locations.extend(region["search_locations"])
    return _unique(locations)


def dama_region_config() -> list[dict[str, Any]]:
    return [dict(region) for region in DAMA_REGION_CONFIG]


def match_dama_region(location: str) -> dict[str, Any]:
    text = f" {str(location or '').strip().lower()} "
    for region in DAMA_REGION_CONFIG:
        for term in region["match_terms"]:
            needle = f" {str(term).strip().lower()} " if str(term).strip().lower().startswith(("wa", "sa", "nt", "vic", "qld", "nsw")) else str(term).strip().lower()
            if needle and needle in text:
                return {
                    "matched": True,
                    "region": region["name"],
                    "state": region["state"],
                    "priority": region["priority"],
                    "weight": region["weight"],
                    "matched_term": term,
                }
    # State abbreviations are ambiguous globally (WA can be Washington), so
    # accept them only when the source has explicitly established Australia.
    if "australia" in text:
        state_routes = {
            "wa": "Western Australia State DAMA",
            "nt": "Northern Territory DAMA",
            "sa": "South Australia Regional",
        }
        for state_code, region_name in state_routes.items():
            if not re.search(rf"\b{state_code}\b", text):
                continue
            region = next(item for item in DAMA_REGION_CONFIG if item["name"] == region_name)
            return {
                "matched": True,
                "region": region["name"],
                "state": region["state"],
                "priority": region["priority"],
                "weight": region["weight"],
                "matched_term": f"{state_code.upper()} + Australia",
            }
    return {"matched": False, "region": "", "state": "", "priority": 0, "weight": 0.0, "matched_term": ""}


def sa_dama_visa_queries() -> list[str]:
    include = os.environ.get("JOB_FILTER_SA_DAMA_INCLUDE_VISA_QUERIES", "1").strip().lower()
    if include in {"0", "false", "no", "off"}:
        return []
    return _unique(_split_env_list("JOB_FILTER_SA_DAMA_VISA_QUERIES") or list(SA_DAMA_VISA_QUERIES))


def build_sa_dama_config(base: JobFilterConfig | None = None) -> JobFilterConfig:
    cfg = base or JobFilterConfig()

    cfg.min_monthly_usd = int(os.environ.get("JOB_FILTER_SA_DAMA_MIN_MONTHLY_USD", "0") or "0")
    cfg.geo_priority_bonus = max(cfg.geo_priority_bonus, 2)
    cfg.company_priority_bonus = max(cfg.company_priority_bonus, 2)

    cfg.top_roles.update(role.lower() for role in SA_DAMA_ROLES)
    cfg.medium_roles.update(role.lower() for role in SA_DAMA_ROLES)
    cfg.top_domains.update(
        {
            "gas",
            "oil and gas",
            "mining",
            "copper",
            "uranium",
            "water",
            "wastewater",
            "utilities",
            "defence",
            "submarine",
            "steel",
            "smelter",
            "industrial infrastructure",
            "brownfield",
            "process plant",
            "power generation",
        }
    )
    cfg.top_technical.update(
        {
            "operations readiness",
            "operational readiness",
            "asset integrity",
            "asset management",
            "maintenance strategy",
            "reliability",
            "start up",
            "startup",
            "brownfield",
            "maintenance superintendent",
            "maintenance engineering",
            "sap pm",
            "cmms",
            "rcm",
            "rca",
            "iso 55001",
        }
    )
    cfg.medium_signals.update(
        {
            "operations readiness",
            "operational readiness",
            "asset integrity",
            "asset management",
            "maintenance",
            "reliability",
            "brownfield",
            "plant",
            "engineering",
        }
    )
    cfg.geo_priority.update(term.lower() for region in DAMA_REGION_CONFIG for term in region["match_terms"])
    cfg.geo_priority.update(location.lower() for region in DAMA_REGION_CONFIG for location in region["search_locations"])
    cfg.company_priority.update(company.lower() for company in SA_DAMA_COMPANIES)
    cfg.visa_required_geo.update(cfg.geo_priority)
    cfg.visa_signals.update(signal.lower() for signal in SA_DAMA_VISA_QUERIES)
    cfg.visa_signals.update(
        {
            "sponsorship considered",
            "sponsorship available",
            "employer nomination",
            "regional sponsored",
            "skilled employer sponsored regional",
            "subclass 482",
            "subclass 186",
            "subclass 494",
            "sid visa",
        }
    )

    # These are legitimate target sectors for South Australia DAMA searches.
    cfg.hard_exclusions.difference_update(
        {
            "water",
            "wastewater",
            "power generation",
            "power distribution",
            "chemical",
            "chemical manufacturing",
            "infrastructure",
            "mining",
            "marine",
            "aerospace",
        }
    )
    return cfg
