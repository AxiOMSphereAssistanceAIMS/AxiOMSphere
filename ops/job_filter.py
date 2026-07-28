from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Priority(str, Enum):
    HIGH = "HIGH PRIORITY"
    HIGH_DIGITAL = "HIGH PRIORITY (DIGITAL)"
    MEDIUM = "MEDIUM PRIORITY"
    IGNORE = "IGNORE"


@dataclass
class JobFilterConfig:
    # Minimum monthly salary in USD — any posting below this is IGNORE
    # (_extract_salary converts all currencies to USD)
    min_monthly_usd: int = 12_000
    geo_priority_bonus: int = 1
    company_priority_bonus: int = 1

    top_roles: set[str] = field(
        default_factory=lambda: {
            # Management / Leadership
            "maintenance manager",
            "asset integrity manager",
            "reliability manager",
            "head of maintenance",
            "head of asset integrity",
            "head of reliability",
            "technical authority",
            "lead maintenance",
            "lead reliability",
            "lead instrument",
            "lead integrity",
            "maintenance lead",
            "integrity lead",
            "reliability lead",
            "principal engineer",
            "principal integrity engineer",
            "principal instrument engineer",
            "principal reliability engineer",
            "principal maintenance engineer",
            "technical lead",
            "technical leader",
            "senior manager",
            "maintenance expert",
            "lead maintenance expert",
            "maintenance startup manager",
            "sme",
            "subject matter expert",
            # Specialist senior roles
            "senior engineer",
            "senior integrity engineer",
            "senior instrument engineer",
            "lead engineer",
            "lead planning engineer",
            "maintenance planning manager",
            "asset manager",
        }
    )
    top_domains: set[str] = field(
        default_factory=lambda: {
            "oil and gas",
            "energy",
            "petrochemical",
            "refinery",
            "upstream",
            "onshore",
            "offshore",
            "process plant",
            "lng",
            "fpso",
            "pipeline",
        }
    )
    top_technical: set[str] = field(
        default_factory=lambda: {
            # CMMS / Asset Management
            "sap pm",
            "sap mm",
            "sap qm",
            "cmms",
            "iso 55001",
            # Reliability methods
            "rcm",
            "fmeca",
            "rca",
            "pdm",
            "cbm",
            "lean six sigma",
            "six sigma",
            "dmaic",
            "mtbf",
            # Safety Critical / Integrity
            "sce",
            "performance standards",
            "technical integrity",
            "asset integrity",
            # Functional Safety / ICSS
            "iec 61511",
            "sis",
            "sif",
            "functional safety",
            "icss",
            "dcs",
            "esd",
            "f and g",
            "hipps",
            "i and c",
            "instrumentation and control",
            # Alarm Management
            "alarm management",
            "eemua",
            "eemua 191",
            "isa 18 2",
            # Operational
            "operational readiness",
            "operations readiness",
            "iso 14224",
        }
    )
    medium_roles: set[str] = field(
        default_factory=lambda: {
            "senior maintenance engineer",
            "senior reliability engineer",
            "senior instrument engineer",
            "senior integrity engineer",
            "maintenance engineer",
            "reliability engineer",
            "reliability lead",
            "maintenance lead",
            "principal engineer",
            "principal integrity engineer",
            "technical lead",
            "integrity engineer",
            "asset engineer",
            "instrument engineer",
            "maintenance specialist",
            "maintenance planner",
            "planning engineer",
            "senior engineer",
            "senior planner",
            "cmms specialist",
            "sap specialist",
            "integrity specialist",
            "reliability specialist",
            "functional safety engineer",
            "safety engineer",
        }
    )
    medium_signals: set[str] = field(
        default_factory=lambda: {
            "maintenance",
            "asset integrity",
            "integrity",
            "reliability",
            "asset management",
            "instrument",
            "functional safety",
            "cmms",
            "sap pm",
        }
    )
    digital_signals: set[str] = field(
        default_factory=lambda: {
            "ai",
            "machine learning",
            "data analytics",
            "predictive",
            "llm",
            "industrial ai",
            "digital twin",
        }
    )
    digital_context: set[str] = field(
        default_factory=lambda: {
            "maintenance",
            "reliability",
            "asset",
            "integrity",
            "industrial",
        }
    )
    hard_exclusions: set[str] = field(
        default_factory=lambda: {
            # ── Trade / junior / entry-level positions ──
            "electrical",
            "infrastructure",
            "assistant",
            "interface",
            "field engineer",
            "civil",
            "technician",
            "senior technician",
            "junior technician",
            "junior",
            "junior engineer",
            "entry level",
            "graduate",
            "graduate engineer",
            "fresh graduate",
            "intern",
            "internship",
            "trainee",
            "apprentice",
            "helper",
            "laborer",
            "labourer",
            "supervisor",
            "foreman",
            "operator",
            "field operator",
            "plant operator",
            "welder",
            "fitter",
            "machinist",
            "plumber",
            "rigger",
            "scaffolder",
            "painter",
            "insulator",
            "construction",
            "architect",
            # ── Non-profile IT / software ──
            "cloud",
            "cloud engineer",
            "software developer",
            "software development",
            "software engineering",
            "site reliability engineer",
            "site reliability",
            "platform systems",
            "command and control",
            "presales",
            "frontend",
            "backend",
            "fullstack",
            "devops",
            "cybersecurity",
            "it support",
            "helpdesk",
            "it software",
            # ── Non-profile industries ──
            "insurance",
            "real estate",
            "hospitality",
            "sales",
            "sales engineer",
            "sales manager",
            "account manager",
            "business development",
            "logistics",
            "supply chain",
            "business consulting",
            "consulting",
            "delivery manager",
            # ── Transport / aviation ──
            "railway",
            "rail",
            "metro rail",
            "train station",
            "airline",
            "airlines",
            "aviation",
            "airport",
            "aircraft",
            "aerospace",
            "fleet management",
            "ground handling",
            "cabin crew",
            "pilot",
            # ── Pharma / misc ──
            "pharmaceutical",
            "pharmaceuticals",
            "pharma",
            "security",
            "cctv",
            "chemical",
            "chemical manufacturing",
            "water",
            "wastewater",
            "power generation",
            "power distribution",
            "engine",
            "property",
            "campus",
            "12 hours shift",
            "12 hour shift",
            "56 shift",
            "no longer accepting applications",
            "arabic",
            "national",
            "nationalization",
            "maximo",
            "elevator",
            "hvac",
            "flydubai",
            "fly dubai",
            "plastic manufacturing",
            "cold storage",
            "coldstorage",
            "mining",
            "rotating equipment",
            "blade",
            "blades",
            "fraud",
            "hotel",
            "marine",
            "drydocks",
            "hospital",
            "facility",
            "facilities",
            "facilities management",
            "high school diploma",
            "native arabic",
            "properties",
            # ── Excluded geo ──
            "riyadh",
            "china",
            "beijing",
            "shanghai",
            "shenzhen",
            "guangzhou",
            "chinese",
        }
    )
    # ── Title-only exclusions (matched against job title, not full text) ──
    title_exclusions: set[str] = field(
        default_factory=lambda: {
            "software development",
            "software developer",
            "mechanical maintenance",
            "hardware software",
            "hw sw",
            # Pure single-discipline mechanical engineering titles (e.g.
            # "Reliability & Project Engineer (Mechanical)") — distinct from
            # reliability/maintenance leadership roles that merely mention
            # mechanical equipment in the body text. normalize_text() strips
            # punctuation, so this matches regardless of word order or the
            # parentheses around the discipline qualifier.
            "mechanical",
        }
    )
    # ── Content-only exclusions (matched against description body, not title) ──
    content_exclusions: set[str] = field(
        default_factory=lambda: set()
    )
    # Maximum years of experience in job posting below which we IGNORE (entry-level filter)
    min_experience_years: int = 10
    conditional_exclusions: set[str] = field(default_factory=lambda: {"supervisor", "coordinator"})
    seniority_whitelist: set[str] = field(default_factory=lambda: {"senior"})
    geo_priority: set[str] = field(default_factory=lambda: {"uae", "ksa", "qatar", "saudi arabia"})
    company_priority: set[str] = field(default_factory=lambda: {"adnoc", "aramco"})
    # Non-Gulf regions requiring work permits — visa sponsorship boosts to HIGH, without → cap MEDIUM
    visa_required_geo: set[str] = field(default_factory=lambda: {
        # Australia
        "australia", "sydney", "melbourne", "brisbane", "perth", "adelaide",
        "queensland", "victoria", "new south wales",
        # Malaysia / Borneo
        "malaysia", "kuala lumpur", "borneo", "sabah", "sarawak",
        "penang", "johor",
        # Singapore
        "singapore",
        # USA
        "united states", "usa", "houston", "texas", "california",
        "new york", "denver", "colorado", "louisiana", "oklahoma",
        "alaska", "north dakota", "new jersey", "pennsylvania",
        "illinois", "ohio", "michigan", "florida", "washington",
    })
    visa_signals: set[str] = field(default_factory=lambda: {
        # General
        "visa sponsorship", "sponsor visa", "sponsored visa",
        "work permit", "work authorization", "relocation assistance",
        "relocation package", "relocation support",
        # Australia
        "employer sponsored visa", "ens 186", "186 visa",
        "482 visa", "tss visa", "skilled worker visa",
        # USA
        "h1b", "h 1b", "h1 b", "green card", "ead",
        "tn visa", "e2 visa", "l1 visa", "o1 visa",
        "will sponsor", "sponsorship available", "sponsorship provided",
        # Singapore
        "employment pass", "ep holder", "s pass",
        # Malaysia
        "expatriate", "expat package",
    })


@dataclass
class ClassificationResult:
    priority: Priority
    score: int
    reasons: list[str]
    matched_roles: list[str]
    matched_domains: list[str]
    matched_technical: list[str]
    matched_digital: list[str]
    salary_text: str | None = None
    salary_monthly_usd: float | None = None
    salary_annual_usd: float | None = None
    geo_boost: bool = False
    company_boost: bool = False
    visa_sponsored: bool = False
    visa_region: bool = False


def normalize_text(text: str) -> str:
    t = text.lower()
    t = t.replace("&", " and ")
    t = t.replace("/", " ")
    t = t.replace("-", " ")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _match_terms(text_norm: str, terms: set[str]) -> list[str]:
    out: list[str] = []
    for term in sorted(terms):
        if re.search(rf"\b{re.escape(term)}\b", text_norm):
            out.append(term)
    return out


def _extract_salary(text_norm: str) -> tuple[str | None, float | None, float | None]:
    """Extract salary and convert to USD monthly / USD annual.

    Supports: AED, USD, SAR, QAR, SGD, AUD, MYR, RM, generic $.
    Formats:  "AED 35,000 monthly", "$3,500 to $4,000 Monthly",
              "SGD 8000 per month", "120,000 AED per year".
    When a range is found (X to Y), we take the HIGHER value (Y).
    """
    salary_text = None
    monthly_usd: float | None = None
    annual_usd: float | None = None

    # Approximate FX rates to USD (as of 2026)
    _FX_TO_USD = {
        "usd": 1.0, "$": 1.0,
        "aed": 0.2723,   # 1 AED ≈ 0.27 USD
        "sar": 0.2667,   # 1 SAR ≈ 0.27 USD
        "qar": 0.2747,   # 1 QAR ≈ 0.27 USD
        "sgd": 0.75,     # 1 SGD ≈ 0.75 USD
        "aud": 0.65,     # 1 AUD ≈ 0.65 USD
        "myr": 0.22,     # 1 MYR ≈ 0.22 USD
        "rm": 0.22,      # RM = MYR
    }
    _CCY = r"(?:aed|usd|sar|qar|sgd|aud|myr|rm|\$)"
    _NUM = r"[0-9][0-9,\.]*"
    _MONTH = r"(?:per month|monthly|month|/month|p\.m\.)"
    _YEAR = r"(?:per year|annual|annually|yearly|/year|p\.a\.)"

    def _to_num(x: str) -> float:
        return float(x.replace(",", ""))

    def _to_usd(amount: float, ccy: str) -> float:
        return amount * _FX_TO_USD.get(ccy.lower().strip(), 1.0)

    # --- Monthly patterns ---
    # "CCY X to Y monthly" or "CCY X monthly"
    m_range = re.search(
        rf"({_CCY})\s*({_NUM})\s*(?:to|-)\s*(?:{_CCY})?\s*({_NUM})\s*{_MONTH}",
        text_norm,
    )
    m_single1 = re.search(rf"({_CCY})\s*({_NUM})\s*{_MONTH}", text_norm)
    m_single2 = re.search(rf"({_NUM})\s*({_CCY})\s*{_MONTH}", text_norm)

    if m_range:
        ccy = m_range.group(1)
        high = _to_num(m_range.group(3))
        monthly_usd = _to_usd(high, ccy)
        salary_text = m_range.group(0)
    elif m_single1:
        ccy = m_single1.group(1)
        monthly_usd = _to_usd(_to_num(m_single1.group(2)), ccy)
        salary_text = m_single1.group(0)
    elif m_single2:
        ccy = m_single2.group(2)
        monthly_usd = _to_usd(_to_num(m_single2.group(1)), ccy)
        salary_text = m_single2.group(0)

    # --- Annual patterns ---
    y_range = re.search(
        rf"({_CCY})\s*({_NUM})\s*(?:to|-)\s*(?:{_CCY})?\s*({_NUM})\s*{_YEAR}",
        text_norm,
    )
    y_single1 = re.search(rf"({_CCY})\s*({_NUM})\s*{_YEAR}", text_norm)
    y_single2 = re.search(rf"({_NUM})\s*({_CCY})\s*{_YEAR}", text_norm)

    if y_range:
        ccy = y_range.group(1)
        high = _to_num(y_range.group(3))
        annual_usd = _to_usd(high, ccy)
        salary_text = y_range.group(0)
    elif y_single1:
        ccy = y_single1.group(1)
        annual_usd = _to_usd(_to_num(y_single1.group(2)), ccy)
        salary_text = y_single1.group(0)
    elif y_single2:
        ccy = y_single2.group(2)
        annual_usd = _to_usd(_to_num(y_single2.group(1)), ccy)
        salary_text = y_single2.group(0)

    return salary_text, monthly_usd, annual_usd


def _extract_max_experience(text_norm: str) -> int | None:
    """
    Extract the maximum years of experience mentioned in a job posting.
    Returns None if no experience requirement found.

    Patterns matched:
      "5 to 8 years" → 8
      "3 5 years experience" → 5
      "minimum 5 years" → 5
      "at least 7 years" → 7
      "5 years of experience" → 5
      "experience 3 to 6 years" → 6
    """
    candidates: list[int] = []

    # "X to Y years" / "X - Y years"
    for m in re.finditer(r"(\d{1,2})\s*(?:to|–|—|-)\s*(\d{1,2})\s*(?:\+\s*)?year", text_norm):
        candidates.append(int(m.group(2)))

    # "minimum X years" / "at least X years" / "X+ years"
    for m in re.finditer(r"(?:minimum|at least|min)\s*(\d{1,2})\s*(?:\+\s*)?year", text_norm):
        candidates.append(int(m.group(1)))
    for m in re.finditer(r"(\d{1,2})\+\s*years?", text_norm):
        candidates.append(int(m.group(1)))

    # "X years of experience" / "X years experience" / "X years in <domain>"
    for m in re.finditer(r"(\d{1,2})\s*years?\s*(?:of\s+)?experience", text_norm):
        candidates.append(int(m.group(1)))
    for m in re.finditer(r"(\d{1,2})\s*years?\s*(?:of\s+)?(?:in|of)\s+(?:maintenance|reliability|integrity|engineering|oil|energy|industrial)", text_norm):
        candidates.append(int(m.group(1)))

    # Filter out unrealistic values (>40)
    candidates = [c for c in candidates if 0 < c <= 40]
    return max(candidates) if candidates else None


def classify_job(raw_text: str, config: JobFilterConfig | None = None, *, title: str = "") -> ClassificationResult:
    cfg = config or JobFilterConfig()
    text = normalize_text(raw_text)
    title_norm = normalize_text(title) if title else ""
    reasons: list[str] = []

    # Salary extraction runs on lightly-normalized text (preserve $, /, .)
    _salary_raw = raw_text.lower().replace("&", " and ")
    _salary_raw = re.sub(r"\s+", " ", _salary_raw).strip()
    salary_text, salary_monthly, salary_annual = _extract_salary(_salary_raw)

    # ── Title-only exclusions ──
    if title_norm:
        title_hits = _match_terms(title_norm, cfg.title_exclusions)
        if title_hits:
            return ClassificationResult(
                priority=Priority.IGNORE, score=0,
                reasons=[f"Title exclusion: {', '.join(title_hits[:4])}"],
                matched_roles=[], matched_domains=[],
                matched_technical=[], matched_digital=[],
                salary_text=salary_text,
                salary_monthly_usd=salary_monthly,
                salary_annual_usd=salary_annual,
            )

    # ── Content-only exclusions (body without title) ──
    body_text = text[len(title_norm):].strip() if title_norm else text
    content_hits = _match_terms(body_text, cfg.content_exclusions)
    if content_hits:
        return ClassificationResult(
            priority=Priority.IGNORE, score=0,
            reasons=[f"Content exclusion: {', '.join(content_hits[:4])}"],
            matched_roles=[], matched_domains=[],
            matched_technical=[], matched_digital=[],
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
        )

    # Conditional exclusions first.
    conditional_hits = _match_terms(text, cfg.conditional_exclusions)
    has_senior = bool(_match_terms(text, cfg.seniority_whitelist))
    if conditional_hits and not has_senior:
        return ClassificationResult(
            priority=Priority.IGNORE,
            score=0,
            reasons=[f"Conditional exclusion without seniority: {', '.join(conditional_hits)}"],
            matched_roles=[],
            matched_domains=[],
            matched_technical=[],
            matched_digital=[],
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
        )

    # Hard exclusions.
    hard_hits = _match_terms(text, cfg.hard_exclusions)
    # Contextual exclusion: "mechanical" is ignored only for trade/non-strategic contexts.
    if re.search(r"\bmechanical\b", text) and _match_terms(
        text,
        {"technician", "supervisor", "foreman", "operator", "welder", "fitter", "machinist"},
    ):
        hard_hits.append("mechanical(trade-context)")
    if hard_hits:
        # Special allowance from spec:
        # "Senior Maintenance Supervisor (Strategic)" can be medium.
        if not (has_senior and "supervisor" in hard_hits and "maintenance" in text):
            return ClassificationResult(
                priority=Priority.IGNORE,
                score=0,
                reasons=[f"Hard exclusion matched: {', '.join(hard_hits[:6])}"],
                matched_roles=[],
                matched_domains=[],
                matched_technical=[],
                matched_digital=[],
                salary_text=salary_text,
                salary_monthly_usd=salary_monthly,
                salary_annual_usd=salary_annual,
            )

    # ── Experience filter: exclude jobs targeting < 10 years experience ──
    # But NOT if digital signals are present (digital transition roles welcome juniors too)
    digital_quick = _match_terms(text, cfg.digital_signals)
    if not digital_quick:
        exp_max = _extract_max_experience(text)
        if exp_max is not None and exp_max < cfg.min_experience_years:
            return ClassificationResult(
                priority=Priority.IGNORE,
                score=0,
                reasons=[f"Experience requirement too low: {exp_max} years (min {cfg.min_experience_years})"],
                matched_roles=[],
                matched_domains=[],
                matched_technical=[],
                matched_digital=[],
                salary_text=salary_text,
                salary_monthly_usd=salary_monthly,
                salary_annual_usd=salary_annual,
            )

    # ── Salary floor: any posting under $12,000 USD/month is IGNORE ──
    _salary_monthly_for_check = salary_monthly
    if _salary_monthly_for_check is None and salary_annual is not None:
        _salary_monthly_for_check = salary_annual / 12.0
    if _salary_monthly_for_check is not None and _salary_monthly_for_check < cfg.min_monthly_usd:
        return ClassificationResult(
            priority=Priority.IGNORE,
            score=0,
            reasons=[f"Salary too low: ${_salary_monthly_for_check:,.0f} USD/month < ${cfg.min_monthly_usd:,}"],
            matched_roles=[],
            matched_domains=[],
            matched_technical=[],
            matched_digital=[],
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
        )

    # ── Non-Gulf visa region detection ──
    # Visa-required regions: with visa signal → keep original priority, without → cap at MEDIUM
    visa_geo_hits = _match_terms(text, cfg.visa_required_geo)
    visa_hits = _match_terms(text, cfg.visa_signals) if visa_geo_hits else []
    is_visa_region = bool(visa_geo_hits)
    has_visa_signal = bool(visa_hits)

    roles = _match_terms(text, cfg.top_roles)
    domains = _match_terms(text, cfg.top_domains)
    technical = _match_terms(text, cfg.top_technical)
    medium_roles = _match_terms(text, cfg.medium_roles)
    medium_signals = _match_terms(text, cfg.medium_signals)
    digital = _match_terms(text, cfg.digital_signals)
    digital_ctx = _match_terms(text, cfg.digital_context)
    geo_hits = _match_terms(text, cfg.geo_priority)
    company_hits = _match_terms(text, cfg.company_priority)

    geo_boost = bool(geo_hits)
    company_boost = bool(company_hits)

    # ── Helper: apply visa-region cap ──
    # In visa-required regions: with visa → keep priority, without visa → cap at MEDIUM
    def _apply_visa_cap(prio: Priority, rsns: list[str]) -> Priority:
        if not is_visa_region:
            return prio
        if has_visa_signal:
            rsns.append(f"Visa region ({', '.join(visa_geo_hits[:2])}) + visa signal: {', '.join(visa_hits[:2])}")
            return prio  # keep HIGH / HIGH_DIGITAL
        # No visa signal → cap at MEDIUM
        if prio in (Priority.HIGH, Priority.HIGH_DIGITAL):
            rsns.append(f"Visa region ({', '.join(visa_geo_hits[:2])}) without visa signal → capped MEDIUM")
            return Priority.MEDIUM
        return prio

    # Priority rule order from spec:
    # exclusion -> digital -> high -> medium -> ignore
    if digital and digital_ctx:
        reasons.append(f"Digital track matched: {', '.join(digital[:3])} + context {', '.join(digital_ctx[:3])}")
        prio = _apply_visa_cap(Priority.HIGH_DIGITAL, reasons)
        return ClassificationResult(
            priority=prio,
            score=12,
            reasons=reasons,
            matched_roles=roles,
            matched_domains=domains,
            matched_technical=technical,
            matched_digital=digital,
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
            geo_boost=geo_boost,
            company_boost=company_boost,
            visa_sponsored=has_visa_signal,
            visa_region=is_visa_region,
        )

    if roles and domains and technical:
        # Salary floor already checked above (min_monthly_usd = $12,000)
        reasons.append("Strict HIGH groups matched: role + domain + technical")
        if salary_text is None:
            reasons.append("Salary not found; include and notify")
        if geo_boost:
            reasons.append(f"Geo priority: {', '.join(geo_hits)}")
        if company_boost:
            reasons.append(f"Company priority: {', '.join(company_hits)}")
        prio = _apply_visa_cap(Priority.HIGH, reasons)
        return ClassificationResult(
            priority=prio,
            score=11 + (cfg.geo_priority_bonus if geo_boost else 0) + (cfg.company_priority_bonus if company_boost else 0),
            reasons=reasons,
            matched_roles=roles,
            matched_domains=domains,
            matched_technical=technical,
            matched_digital=digital,
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
            geo_boost=geo_boost,
            company_boost=company_boost,
            visa_sponsored=has_visa_signal,
            visa_region=is_visa_region,
        )

    if medium_roles and medium_signals:
        reasons.append("MEDIUM matched: medium role + maintenance/reliability signal")
        if geo_boost:
            reasons.append(f"Geo priority: {', '.join(geo_hits)}")
        if company_boost:
            reasons.append(f"Company priority: {', '.join(company_hits)}")
        prio = _apply_visa_cap(Priority.MEDIUM, reasons)
        return ClassificationResult(
            priority=prio,
            score=7 + (cfg.geo_priority_bonus if geo_boost else 0) + (cfg.company_priority_bonus if company_boost else 0),
            reasons=reasons,
            matched_roles=medium_roles,
            matched_domains=domains,
            matched_technical=technical,
            matched_digital=digital,
            salary_text=salary_text,
            salary_monthly_usd=salary_monthly,
            salary_annual_usd=salary_annual,
            geo_boost=geo_boost,
            company_boost=company_boost,
            visa_sponsored=has_visa_signal,
            visa_region=is_visa_region,
        )

    # Fallback weighted scoring
    score = 0
    if roles:
        score += 5
    if domains:
        score += 3
    if technical:
        score += 3
    if digital and digital_ctx:
        score += 4
    if geo_boost:
        score += cfg.geo_priority_bonus
    if company_boost:
        score += cfg.company_priority_bonus

    if score >= 10:
        priority = Priority.HIGH
    elif score >= 5:
        priority = Priority.MEDIUM
    else:
        priority = Priority.IGNORE
    priority = _apply_visa_cap(priority, reasons)
    reasons.append(f"Fallback weighted score: {score}")
    return ClassificationResult(
        priority=priority,
        score=score,
        reasons=reasons,
        matched_roles=roles or medium_roles,
        matched_domains=domains,
        matched_technical=technical,
        matched_digital=digital,
        salary_text=salary_text,
        salary_monthly_usd=salary_monthly,
        salary_annual_usd=salary_annual,
        geo_boost=geo_boost,
        company_boost=company_boost,
        visa_sponsored=has_visa_signal,
        visa_region=is_visa_region,
    )
