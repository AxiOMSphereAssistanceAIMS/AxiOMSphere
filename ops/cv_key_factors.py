"""
cv_key_factors.py
─────────────────
Извлечение структурированных ключевых факторов из резюме и
процентный скоринг совпадения с описанием вакансии.

Публичный API:
    from cv_key_factors import extract_key_factors, score_job_match, CvKeyFactors

    kf = extract_key_factors(cv_text_or_CvData)   # async variant: await extract_key_factors_async(...)
    result = score_job_match(kf, job_dict)         # returns MatchResult(score=85, breakdown={...})

Пороги уведомлений:
    80-100 → срочный алерт в Telegram (сразу)
    50-79  → утренний дайджест
    < 50   → не показывать
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

log = logging.getLogger("cv_key_factors")

# ── Thresholds ──────────────────────────────────────────────────────────────

URGENT_THRESHOLD = 80    # 80-100: immediate alert
DIGEST_THRESHOLD = 50    # 50-79: morning digest
DROP_THRESHOLD   = 50    # < 50: drop

# ── Scoring weights (must sum to 100) ───────────────────────────────────────

_WEIGHTS = {
    "role":           30,   # job title ↔ target roles
    "skills":         25,   # required skills ↔ candidate skills + domain systems
    "industry":       15,   # sector match (oil_gas, offshore, mining, etc.)
    "certifications": 15,   # required certs ↔ candidate certs
    "location":       10,   # geography
    "seniority":       5,   # level match (senior/lead/manager)
}

# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class CvKeyFactors:
    """Structured key factors extracted from a CV for job matching."""
    # Role
    target_roles: list[str] = field(default_factory=list)   # ["maintenance manager", "reliability engineer"]
    seniority: str = ""                                       # senior | lead | manager | specialist | engineer
    # Industry
    industries: list[str] = field(default_factory=list)      # ["oil_gas", "offshore", "petrochemical"]
    work_type: list[str] = field(default_factory=list)       # ["onshore", "offshore", "both"]
    # Skills
    tech_skills: list[str] = field(default_factory=list)     # top 20 technical skills
    domain_systems: list[str] = field(default_factory=list)  # SAP PM, Maximo, Aveva, etc.
    # Credentials
    certifications: list[str] = field(default_factory=list)  # API 580, NEBOSH, ISO 55001, etc.
    languages: list[str] = field(default_factory=list)       # ["English (fluent)", "Russian (native)"]
    # Experience
    years_experience: int = 0
    # Geography
    geo_preferences: list[str] = field(default_factory=list) # ["UAE", "Qatar", "Australia", "KSA"]
    # Meta
    raw_cv_excerpt: str = ""   # first 300 chars for debug
    extract_ok: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_profile_text(self) -> str:
        """Compact text representation for LLM context."""
        parts = []
        if self.target_roles:
            parts.append(f"Target roles: {', '.join(self.target_roles)}")
        if self.seniority:
            parts.append(f"Seniority: {self.seniority}")
        if self.years_experience:
            parts.append(f"Experience: {self.years_experience}+ years")
        if self.industries:
            parts.append(f"Industries: {', '.join(self.industries)}")
        if self.work_type:
            parts.append(f"Work type: {', '.join(self.work_type)}")
        if self.tech_skills:
            parts.append(f"Skills: {', '.join(self.tech_skills[:15])}")
        if self.domain_systems:
            parts.append(f"Systems: {', '.join(self.domain_systems)}")
        if self.certifications:
            parts.append(f"Certifications: {', '.join(self.certifications)}")
        if self.languages:
            parts.append(f"Languages: {', '.join(self.languages)}")
        if self.geo_preferences:
            parts.append(f"Preferred locations: {', '.join(self.geo_preferences)}")
        return "\n".join(parts)

    def telegram_summary(self) -> str:
        """Human-readable Telegram message."""
        lines = ["🧠 <b>CV Key Factors</b>"]
        if self.target_roles:
            lines.append(f"🎯 <b>Роли:</b> {', '.join(self.target_roles[:5])}")
        if self.seniority:
            lines.append(f"📊 <b>Уровень:</b> {self.seniority}")
        if self.years_experience:
            lines.append(f"⏱ <b>Опыт:</b> {self.years_experience}+ лет")
        if self.industries:
            lines.append(f"🏭 <b>Отрасль:</b> {', '.join(self.industries)}")
        if self.work_type:
            lines.append(f"🚢 <b>Тип работы:</b> {', '.join(self.work_type)}")
        if self.tech_skills:
            sk = ', '.join(self.tech_skills[:10])
            extra = f" (+{len(self.tech_skills)-10})" if len(self.tech_skills) > 10 else ""
            lines.append(f"🔧 <b>Навыки:</b> {sk}{extra}")
        if self.domain_systems:
            lines.append(f"💻 <b>Системы:</b> {', '.join(self.domain_systems[:6])}")
        if self.certifications:
            lines.append(f"📜 <b>Сертификаты:</b> {', '.join(self.certifications[:6])}")
        if self.languages:
            lines.append(f"🌐 <b>Языки:</b> {', '.join(self.languages)}")
        if self.geo_preferences:
            lines.append(f"📍 <b>Регионы:</b> {', '.join(self.geo_preferences)}")
        return "\n".join(lines)


@dataclass
class MatchResult:
    score: int                     # 0–100
    breakdown: dict[str, int]      # {"role": 25, "skills": 20, ...}
    matched_factors: list[str]     # what matched
    missing_factors: list[str]     # what's missing
    tier: str                      # "urgent" | "digest" | "drop"
    summary: str                   # one-line summary

    def telegram_line(self, job: dict) -> str:
        """Compact one-line format for digest."""
        icon = "🔴" if self.score >= URGENT_THRESHOLD else ("🟡" if self.score >= DIGEST_THRESHOLD else "⚫")
        title = job.get("title", "?")[:60]
        company = job.get("company", "")
        url = job.get("url", "")
        loc = job.get("location", "")
        src = job.get("source", "")
        parts = [f"{icon} <b>{self.score}%</b> — <a href='{url}'>{title}</a>"]
        if company:
            parts.append(f"   {company}")
        if loc:
            parts.append(f"   📍 {loc}")
        if src:
            parts.append(f"   🔗 {src}")
        if self.matched_factors:
            parts.append(f"   ✅ {', '.join(self.matched_factors[:3])}")
        if self.missing_factors:
            parts.append(f"   ❌ не найдено: {', '.join(self.missing_factors[:2])}")
        return "\n".join(parts)


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _ollama_url() -> str:
    try:
        from ollama_resolve import effective_ollama_base_url
        return effective_ollama_base_url()
    except Exception:
        return os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _model() -> str:
    return (
        os.environ.get("CV_KEY_FACTORS_MODEL", "").strip()
        or os.environ.get("OMI_CV_MODEL", "").strip()
        or os.environ.get("OMI_MODEL", "").strip()
        or "qwen2.5:14b"
    )


def _llm_extract(cv_text: str) -> CvKeyFactors:
    """Call Ollama to extract structured key factors from CV text."""
    import httpx

    prompt = f"""You are an expert CV analyst. Extract key factors from this CV for job matching.

Return ONLY valid JSON matching this schema exactly:
{{
  "target_roles": ["role1", "role2"],
  "seniority": "senior|lead|manager|specialist|engineer",
  "industries": ["oil_gas", "offshore", "petrochemical", "mining", "power", "construction", "marine"],
  "work_type": ["onshore", "offshore", "both"],
  "tech_skills": ["skill1", "skill2", ...],
  "domain_systems": ["SAP PM", "Maximo", "CMMS", ...],
  "certifications": ["API 580", "NEBOSH", "ISO 55001", ...],
  "languages": ["English (fluent)", ...],
  "years_experience": 15,
  "geo_preferences": ["UAE", "Qatar", "KSA", "Australia", ...]
}}

Rules:
- target_roles: normalize to lowercase, max 8, most important first
- seniority: single word from the enum
- industries: from the allowed list only
- tech_skills: max 20, technical/engineering skills only (not soft skills)
- domain_systems: specific software/systems mentioned
- certifications: exact cert names mentioned, max 10
- years_experience: total years of professional experience as integer
- geo_preferences: countries/regions where candidate worked or explicitly prefers
- Return [] for empty lists, 0 for unknown years

CV TEXT:
{cv_text[:4000]}

JSON ONLY:"""

    try:
        r = httpx.post(
            f"{_ollama_url()}/api/generate",
            json={"model": _model(), "prompt": prompt, "stream": False, "temperature": 0},
            timeout=120.0,
        )
        if r.status_code != 200:
            return CvKeyFactors(error=f"LLM HTTP {r.status_code}", raw_cv_excerpt=cv_text[:300])
        raw = r.json().get("response", "")
        # Extract JSON block
        m = re.search(r"\{[\s\S]+\}", raw)
        if not m:
            return CvKeyFactors(error="no JSON in response", raw_cv_excerpt=cv_text[:300])
        data = json.loads(m.group())
        kf = CvKeyFactors(
            target_roles    = [s.lower().strip() for s in data.get("target_roles", [])],
            seniority       = str(data.get("seniority", "")).lower().strip(),
            industries      = [s.lower().strip() for s in data.get("industries", [])],
            work_type       = [s.lower().strip() for s in data.get("work_type", [])],
            tech_skills     = [s.strip() for s in data.get("tech_skills", [])],
            domain_systems  = [s.strip() for s in data.get("domain_systems", [])],
            certifications  = [s.strip() for s in data.get("certifications", [])],
            languages       = [s.strip() for s in data.get("languages", [])],
            years_experience= int(data.get("years_experience", 0) or 0),
            geo_preferences = [s.strip() for s in data.get("geo_preferences", [])],
            raw_cv_excerpt  = cv_text[:300],
            extract_ok      = True,
        )
        return kf
    except json.JSONDecodeError as e:
        return CvKeyFactors(error=f"JSON parse error: {e}", raw_cv_excerpt=cv_text[:300])
    except Exception as e:
        log.exception("_llm_extract failed")
        return CvKeyFactors(error=str(e), raw_cv_excerpt=cv_text[:300])


# ── Extraction entry points ───────────────────────────────────────────────────

def extract_key_factors(cv_input: Any) -> CvKeyFactors:
    """
    Synchronous extraction. Accepts:
      - str (raw CV text)
      - CvData dataclass from skill_cv_parser
    """
    cv_text = _to_cv_text(cv_input)
    return _llm_extract(cv_text)


async def extract_key_factors_async(cv_input: Any) -> CvKeyFactors:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: extract_key_factors(cv_input))


def _to_cv_text(cv_input: Any) -> str:
    if isinstance(cv_input, str):
        return cv_input
    # CvData or dict
    if hasattr(cv_input, "to_dict"):
        d = cv_input.to_dict()
    elif isinstance(cv_input, dict):
        d = cv_input
    else:
        return str(cv_input)

    parts = []
    if d.get("name"):
        parts.append(f"Name: {d['name']}")
    if d.get("position_target"):
        parts.append(f"Target position: {d['position_target']}")
    if d.get("summary"):
        parts.append(f"Summary: {d['summary']}")
    if d.get("skills"):
        parts.append(f"Skills: {', '.join(d['skills'])}")
    if d.get("certifications"):
        parts.append(f"Certifications: {', '.join(d['certifications'])}")
    if d.get("languages"):
        parts.append(f"Languages: {', '.join(d['languages'])}")
    if d.get("experience"):
        parts.append("Experience:")
        for ex in (d["experience"] or []):
            pos = ex.get("position", "")
            comp = ex.get("company", "")
            s, e = ex.get("start", ""), ex.get("end", "")
            resp = "; ".join((ex.get("responsibilities") or [])[:3])
            parts.append(f"  - {pos} at {comp} ({s}–{e}): {resp}")
    if d.get("education"):
        parts.append("Education:")
        for ed in (d["education"] or []):
            parts.append(f"  - {ed.get('degree','')} {ed.get('field','')} at {ed.get('institution','')} ({ed.get('year','')})")
    if d.get("location"):
        parts.append(f"Location: {d['location']}")
    return "\n".join(parts)


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_job_match(factors: CvKeyFactors, job: dict) -> MatchResult:
    """
    Compute percentage match between CV key factors and a job listing.
    Uses rule-based heuristics — fast, no LLM call needed per job.
    """
    if not factors.extract_ok:
        return MatchResult(
            score=0, breakdown={}, matched_factors=[], missing_factors=["CV not parsed"],
            tier="drop", summary="CV extraction failed",
        )

    title = (job.get("title", "") + " " + job.get("description", "")).lower()
    loc   = job.get("location", "").lower()

    breakdown: dict[str, int] = {}
    matched: list[str] = []
    missing: list[str] = []

    # ── Role match (30 pts) ──────────────────────────────────────────────────
    role_score = 0
    role_words = set(re.findall(r"\b\w{4,}\b", title))
    for role in factors.target_roles:
        role_kw = set(re.findall(r"\b\w{4,}\b", role))
        overlap = len(role_kw & role_words) / max(len(role_kw), 1)
        if overlap >= 0.6:
            role_score = _WEIGHTS["role"]
            matched.append(f"роль: {role}")
            break
        elif overlap >= 0.4 and role_score < _WEIGHTS["role"] // 2:
            role_score = _WEIGHTS["role"] // 2
            matched.append(f"роль (частично): {role}")
    if role_score == 0:
        missing.append("целевая роль")
    breakdown["role"] = role_score

    # ── Skills match (25 pts) ────────────────────────────────────────────────
    skill_hits = 0
    skill_total = max(len(factors.tech_skills) + len(factors.domain_systems), 1)
    all_skills = [(s, True) for s in factors.tech_skills] + [(s, True) for s in factors.domain_systems]
    for skill, _ in all_skills:
        if skill.lower() in title or any(w in title for w in skill.lower().split()):
            skill_hits += 1

    skill_ratio = skill_hits / min(skill_total, 10)  # cap at 10 skills for full score
    skill_score = min(int(skill_ratio * _WEIGHTS["skills"]), _WEIGHTS["skills"])
    breakdown["skills"] = skill_score
    if skill_hits > 0:
        matched.append(f"навыки: {skill_hits}/{min(skill_total,10)}")
    else:
        missing.append("технические навыки")

    # ── Industry match (15 pts) ──────────────────────────────────────────────
    _INDUSTRY_KEYWORDS = {
        "oil_gas":       ["oil", "gas", "petroleum", "lng", "lng", "upstream", "downstream", "refinery", "pipeline"],
        "offshore":      ["offshore", "subsea", "fpso", "platform", "jacket", "topside"],
        "petrochemical": ["petrochemical", "chemical", "polymer", "ethylene"],
        "mining":        ["mining", "mine", "mineral", "metallurgy"],
        "power":         ["power", "energy", "turbine", "generator", "electrical"],
        "construction":  ["construction", "epc", "contractor", "project"],
        "marine":        ["marine", "vessel", "ship", "maritime"],
    }
    industry_score = 0
    for ind in factors.industries:
        kws = _INDUSTRY_KEYWORDS.get(ind, [ind.replace("_", " ")])
        if any(kw in title or kw in loc for kw in kws):
            industry_score = _WEIGHTS["industry"]
            matched.append(f"отрасль: {ind}")
            break
    if industry_score == 0 and factors.industries:
        missing.append("отрасль")
    breakdown["industry"] = industry_score

    # ── Certifications match (15 pts) ────────────────────────────────────────
    cert_hits = 0
    for cert in factors.certifications:
        cert_low = cert.lower()
        # Match on the main cert name/acronym
        cert_tokens = cert_low.split()
        if any(t in title for t in cert_tokens if len(t) >= 3):
            cert_hits += 1
    if cert_hits > 0:
        cert_score = min(int((cert_hits / max(len(factors.certifications), 1)) * _WEIGHTS["certifications"] * 1.5), _WEIGHTS["certifications"])
        matched.append(f"сертификаты: {cert_hits}")
    else:
        cert_score = 0
        # Don't penalise if no certs mentioned in job posting (common)
        if any(kw in title for kw in ["certified", "certification", "nebosh", "api", "iso"]):
            missing.append("сертификаты")
    breakdown["certifications"] = cert_score

    # ── Location match (10 pts) ──────────────────────────────────────────────
    loc_score = 0
    for geo in factors.geo_preferences:
        geo_low = geo.lower()
        if geo_low in loc or geo_low in title:
            loc_score = _WEIGHTS["location"]
            matched.append(f"регион: {geo}")
            break
        # Partial: country code / common abbreviations
        if len(geo_low) <= 3 and geo_low in loc:
            loc_score = _WEIGHTS["location"]
            break
    if loc_score == 0:
        # No penalty if location is not specified in the posting
        if loc and not any(geo.lower() in loc for geo in factors.geo_preferences):
            loc_score = _WEIGHTS["location"] // 2   # partial — at least it's somewhere
    breakdown["location"] = loc_score

    # ── Seniority match (5 pts) ──────────────────────────────────────────────
    sen_kws = {
        "senior":     ["senior", "sr.", "sr "],
        "lead":       ["lead", "leading", "principal"],
        "manager":    ["manager", "head of", "chief", "director"],
        "specialist": ["specialist", "expert", "advisor", "consultant"],
        "engineer":   ["engineer", "engineering"],
    }
    # seniority may be pipe-separated: "manager|senior|lead|expert"
    sen_levels = [s.strip() for s in factors.seniority.lower().split("|") if s.strip()]
    all_sen_kws: list[str] = []
    for sen in sen_levels:
        all_sen_kws.extend(sen_kws.get(sen, [sen]))
    sen_score = _WEIGHTS["seniority"] if any(kw in title for kw in all_sen_kws) else 0
    breakdown["seniority"] = sen_score
    if sen_score > 0:
        matched.append(f"уровень: {'/'.join(sen_levels)}")

    # ── Total ────────────────────────────────────────────────────────────────
    score = sum(breakdown.values())
    score = max(0, min(score, 100))

    tier = (
        "urgent" if score >= URGENT_THRESHOLD
        else "digest" if score >= DIGEST_THRESHOLD
        else "drop"
    )

    top_match = matched[0] if matched else "—"
    summary = f"{score}% совпадение — {top_match}"

    return MatchResult(
        score=score,
        breakdown=breakdown,
        matched_factors=matched,
        missing_factors=missing,
        tier=tier,
        summary=summary,
    )


def score_jobs_batch(factors: CvKeyFactors, jobs: list[dict]) -> list[tuple[dict, MatchResult]]:
    """Score a list of jobs against CV key factors. Returns sorted by score desc."""
    results = [(job, score_job_match(factors, job)) for job in jobs]
    results.sort(key=lambda x: x[1].score, reverse=True)
    return results
