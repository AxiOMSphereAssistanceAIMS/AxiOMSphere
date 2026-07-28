from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _norm(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = (item or "").strip()
        if not value:
            continue
        key = _norm(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _candidate_paths() -> list[Path]:
    raw_paths = []
    for env_name in (
        "JOB_FILTER_RESUME_PROFILE_PATHS",
        "JOB_FILTER_RESUME_PROFILE_PATH",
        "JOB_FILTER_ATS_PROFILE_PATH",
        "JOB_FILTER_CV_KEY_FACTORS_PATH",
    ):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            raw_paths.extend([part.strip() for part in raw.split(",") if part.strip()])

    defaults = [
        # Runtime container paths.
        # Single canonical profile. Older generations are not searched by
        # default; they require an explicit JOB_FILTER_*_PATH override.
        Path("/data/result/cv_master_current_20260727/master_cv.md"),
        Path("/data/result/cv_master_current_20260727/cv_key_factors.json"),
        # Repository-relative host paths.
        _repo_root() / "aims_workspace/result/cv_master_current_20260727/master_cv.md",
        _repo_root() / "result/cv_master_current_20260727/cv_key_factors.json",
        _repo_root() / "aims_workspace/result/cv_master_current_20260727/cv_key_factors.json",
    ]
    candidates = [Path(path).expanduser() for path in raw_paths] + defaults
    return list(dict.fromkeys(candidates))


def _backup_candidate_paths() -> list[Path]:
    # Do not silently revive an older CV generation when the canonical
    # profile is unavailable. Missing canonical evidence must fail closed.
    return []


@dataclass
class ResumeProfile:
    source_paths: list[str] = field(default_factory=list)
    headline: str = ""
    summary: str = ""
    target_roles: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    seniority: str = ""
    keywords: list[str] = field(default_factory=list)
    must_have_in_job_description: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    geo_preferences: list[str] = field(default_factory=list)
    years_experience: int | None = None
    job_search_map: dict[str, Any] = field(default_factory=dict)
    evidence_terms: list[str] = field(default_factory=list)

    def short_summary(self) -> str:
        return (
            f"{len(self.target_roles)} target roles, "
            f"{len(self.keywords)} keywords, "
            f"{len(self.certifications)} certifications, "
            f"{len(self.geo_preferences)} geo preferences"
        )


def _section_text(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    buf: list[str] = []
    target = heading.strip().lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            if capture and current != target:
                break
            capture = current == target
            continue
        if capture:
            buf.append(line)
    return "\n".join(buf).strip()


def _from_master_markdown(markdown: str, profile: ResumeProfile) -> None:
    summary = _section_text(markdown, "professional summary")
    if summary and not profile.summary:
        profile.summary = re.sub(r"\s+", " ", summary).strip()

    core = _section_text(markdown, "core competencies")
    tech = _section_text(markdown, "technical skills")
    for line in "\n".join([core, tech]).splitlines():
        clean = re.sub(r"^\s*[-*•]\s*", "", line).strip()
        if not clean:
            continue
        profile.evidence_terms.append(clean)
        for chunk in re.split(r"[|,:;()–—]", clean):
            chunk = chunk.strip()
            if chunk and len(chunk.split()) <= 6:
                profile.keywords.append(chunk)

    experience = _section_text(markdown, "experience")
    for match in re.finditer(r"^\*\*(.+?)\*\*$", experience, flags=re.MULTILINE):
        title_blob = match.group(1).strip()
        title = title_blob.split("|")[0].strip()
        if title:
            profile.target_roles.append(title)

    if not profile.headline:
        contact = _section_text(markdown, "contact")
        first_line = next((ln.strip() for ln in contact.splitlines() if ln.strip()), "")
        if first_line:
            profile.headline = first_line


def _merge_terms(*groups: list[str]) -> list[str]:
    items: list[str] = []
    for group in groups:
        items.extend(group or [])
    return _unique(items)


def _from_profile_ets(data: dict[str, Any], profile: ResumeProfile) -> None:
    profile.headline = str(data.get("headline", "") or profile.headline).strip()
    summary_bullets = data.get("summary_bullets") or []
    if isinstance(summary_bullets, list):
        profile.summary = " | ".join(str(x).strip() for x in summary_bullets if str(x).strip())
    competencies = data.get("competencies") or []
    if isinstance(competencies, list):
        for comp in competencies:
            if isinstance(comp, dict):
                name = str(comp.get("name", "") or "").strip()
                if name:
                    profile.evidence_terms.append(name)
                evidences = comp.get("evidence") or []
                if isinstance(evidences, list):
                    for ev in evidences:
                        if isinstance(ev, dict):
                            quote = str(ev.get("quote", "") or "").strip()
                            if quote:
                                profile.evidence_terms.append(quote)
    themes = data.get("experience_themes") or []
    if isinstance(themes, list):
        for theme in themes:
            if isinstance(theme, dict):
                profile.evidence_terms.extend(str(x).strip() for x in theme.get("keywords", []) if str(x).strip())


def _from_cv_key_factors(data: dict[str, Any], profile: ResumeProfile) -> None:
    profile.target_roles = _merge_terms(profile.target_roles, list(data.get("target_roles") or []))
    profile.industries = _merge_terms(profile.industries, list(data.get("industries") or []))
    profile.seniority = str(data.get("seniority", "") or profile.seniority).strip()
    profile.keywords = _merge_terms(profile.keywords, list(data.get("tech_skills") or []), list(data.get("domain_systems") or []))
    profile.certifications = _merge_terms(profile.certifications, list(data.get("certifications") or []))
    profile.geo_preferences = _merge_terms(profile.geo_preferences, list(data.get("geo_preferences") or []))
    years = data.get("years_experience")
    if profile.years_experience is None and isinstance(years, int):
        profile.years_experience = years


def _from_ats_map(data: dict[str, Any], profile: ResumeProfile) -> None:
    job_search_map = data.get("job_search_map") or {}
    if not isinstance(job_search_map, dict):
        return
    profile.job_search_map = {
        key: list(value) if isinstance(value, list) else value
        for key, value in job_search_map.items()
    }
    profile.target_roles = _merge_terms(profile.target_roles, list(job_search_map.get("target_roles") or []))
    profile.industries = _merge_terms(profile.industries, list(job_search_map.get("industries") or []))
    profile.keywords = _merge_terms(
        profile.keywords,
        list(job_search_map.get("keywords_for_job_sites") or []),
        list(job_search_map.get("must_have_in_job_description") or []),
        list(job_search_map.get("nice_to_have") or []),
    )
    profile.must_have_in_job_description = _merge_terms(
        profile.must_have_in_job_description,
        list(job_search_map.get("must_have_in_job_description") or []),
    )
    profile.nice_to_have = _merge_terms(profile.nice_to_have, list(job_search_map.get("nice_to_have") or []))
    profile.exclude_keywords = _merge_terms(profile.exclude_keywords, list(job_search_map.get("exclude_keywords") or []))
    profile.seniority = str(job_search_map.get("seniority", "") or profile.seniority).strip()


def load_resume_profile() -> ResumeProfile | None:
    profile = ResumeProfile()
    seen_any = False
    for path in _candidate_paths():
        data = _read_json(path)
        text_data = ""
        if not data:
            if path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
                try:
                    text_data = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    text_data = ""
            else:
                continue
        seen_any = True
        profile.source_paths.append(str(path))
        if text_data and "master_cv" in path.name.lower():
            _from_master_markdown(text_data, profile)
        if data is None:
            continue
        if "job_search_map" in data:
            _from_ats_map(data, profile)
        if "target_roles" in data or "tech_skills" in data or "domain_systems" in data:
            _from_cv_key_factors(data, profile)
        if "headline" in data or "competencies" in data or "experience_themes" in data:
            _from_profile_ets(data, profile)

    primary_looks_useful = bool(
        profile.target_roles or profile.keywords or profile.certifications or profile.geo_preferences or profile.evidence_terms
    )
    if not primary_looks_useful:
        for path in _backup_candidate_paths():
            data = _read_json(path)
            if not data:
                continue
            seen_any = True
            profile.source_paths.append(str(path))
            if "headline" in data or "competencies" in data or "experience_themes" in data:
                _from_profile_ets(data, profile)
            if profile.target_roles or profile.keywords or profile.certifications or profile.geo_preferences or profile.evidence_terms:
                break

    if not seen_any:
        return None

    profile.target_roles = _unique(profile.target_roles)
    profile.industries = _unique(profile.industries)
    profile.keywords = _unique(profile.keywords)
    profile.must_have_in_job_description = _unique(profile.must_have_in_job_description)
    profile.nice_to_have = _unique(profile.nice_to_have)
    profile.exclude_keywords = _unique(profile.exclude_keywords)
    profile.certifications = _unique(profile.certifications)
    profile.geo_preferences = _unique(profile.geo_preferences)
    profile.evidence_terms = _unique(profile.evidence_terms)
    return profile


def _contains_any(text: str, terms: list[str]) -> list[str]:
    haystack = _norm(text)
    matches: list[str] = []
    for term in terms:
        for needle in _term_variants(term):
            if needle and needle in haystack:
                matches.append(term)
                break
    return _unique(matches)


def _contains_role_terms(text: str, terms: list[str]) -> list[str]:
    """Match exact role phrases plus ordered-title variants.

    For example, ``maintenance manager`` must match
    ``Maintenance & Engineering Manager`` without making a generic
    ``engineering lead`` match every engineering vacancy.
    """
    exact = _contains_any(text, terms)
    matched = {_norm(item) for item in exact}
    haystack_tokens = _tokenize(text)
    for term in terms:
        normalized = _norm(term)
        if normalized in matched:
            continue
        role_tokens = _tokenize(normalized)
        if len(role_tokens) >= 2 and role_tokens.issubset(haystack_tokens):
            exact.append(term)
            matched.add(normalized)
    return _unique(exact)


def _seniority_hits(text: str, seniority: str) -> list[str]:
    terms = [item.strip() for item in re.split(r"[|,;/]+", seniority or "") if item.strip()]
    return _contains_any(text, terms)


def _term_variants(term: str) -> list[str]:
    raw = _norm(term)
    if not raw:
        return []
    variants = {
        raw,
        raw.replace("_", " "),
        raw.replace("_", " & "),
        raw.replace("/", " "),
        raw.replace("-", " "),
        re.sub(r"[^a-z0-9]+", " ", raw),
    }
    return [variant for variant in _unique([re.sub(r"\s+", " ", v).strip() for v in variants]) if variant]


def _tokenize(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9][a-z0-9&+.-]{1,}", _norm(text)):
        token = token.strip("+-./&")
        if len(token) < 2:
            continue
        if token in {"and", "for", "the", "with", "from", "into", "via", "of", "in", "to"}:
            continue
        tokens.add(token)
    return tokens


def _profile_token_lexicon(profile: ResumeProfile) -> set[str]:
    texts = [
        profile.headline,
        profile.summary,
        *profile.target_roles,
        *profile.industries,
        *profile.keywords,
        *profile.must_have_in_job_description,
        *profile.nice_to_have,
        *profile.certifications,
        *profile.geo_preferences,
        *profile.evidence_terms,
    ]
    lexicon: set[str] = set()
    for text in texts:
        lexicon.update(_tokenize(text))
    return lexicon


def score_job_against_resume(job: dict[str, Any], profile: ResumeProfile | None) -> tuple[float, list[str], dict[str, list[str]]]:
    if profile is None:
        return 0.0, ["resume profile not loaded"], {}

    text = " ".join(
        str(job.get(field, "") or "")
        for field in ("title", "company", "description", "location", "source", "industry")
    )

    role_hits = _contains_role_terms(text, profile.target_roles)
    industry_hits = _contains_any(text, profile.industries)
    keyword_hits = _contains_any(text, profile.keywords)
    cert_hits = _contains_any(text, profile.certifications)
    geo_hits = _contains_any(text, profile.geo_preferences)
    evidence_hits = _contains_any(text, profile.evidence_terms)
    token_hits = sorted(_tokenize(text) & _profile_token_lexicon(profile))

    score = 0.0
    reasons: list[str] = []
    buckets: dict[str, list[str]] = {
        "roles": role_hits,
        "industries": industry_hits,
        "keywords": keyword_hits,
        "certifications": cert_hits,
        "geo": geo_hits,
        "evidence": evidence_hits,
        "tokens": token_hits,
    }

    if role_hits:
        score += min(2.5, 1.2 + 0.4 * max(0, len(role_hits) - 1))
        reasons.append(f"role match: {', '.join(role_hits[:3])}")
    if industry_hits:
        score += min(1.5, 0.75 * len(industry_hits))
        reasons.append(f"industry match: {', '.join(industry_hits[:3])}")
    if token_hits:
        score += min(4.0, 0.35 * len(token_hits))
        reasons.append(f"token overlap: {', '.join(token_hits[:8])}")
    if keyword_hits:
        score += min(1.5, 0.25 * len(keyword_hits))
        reasons.append(f"keyword match: {', '.join(keyword_hits[:5])}")
    if cert_hits:
        score += min(1.0, 0.5 * len(cert_hits))
        reasons.append(f"certification match: {', '.join(cert_hits[:3])}")
    if geo_hits:
        score += min(0.8, 0.4 * len(geo_hits))
        reasons.append(f"geo match: {', '.join(geo_hits[:3])}")
    if evidence_hits:
        score += min(0.8, 0.2 * len(evidence_hits))
        reasons.append(f"profile evidence match: {', '.join(evidence_hits[:4])}")

    seniority_hits = _seniority_hits(text, profile.seniority)
    if seniority_hits:
        score += 0.5
        reasons.append(f"seniority match: {', '.join(seniority_hits)}")

    score = round(min(10.0, score), 1)
    if not reasons:
        reasons.append("no resume-specific matches")
    return score, reasons, buckets


def resume_match_percent(job: dict[str, Any], profile: ResumeProfile | None) -> tuple[float, dict[str, Any]]:
    """Return a transparent, lightweight ATS-style coverage percentage.

    This is deliberately separate from ``display_score_10``: the latter is an
    opportunity-ranking heuristic and must not be presented as resume fit.
    """
    if profile is None:
        return 0.0, {"profile_loaded": False, "reason": "resume profile not loaded"}
    text = " ".join(str(job.get(k, "") or "") for k in ("title", "description", "requirements", "responsibilities", "industry"))
    role_hits = _contains_role_terms(text, profile.target_roles)
    keyword_hits = _contains_any(text, profile.keywords)
    industry_hits = _contains_any(text, profile.industries)
    cert_hits = _contains_any(text, profile.certifications)
    evidence_hits = _contains_any(text, profile.evidence_terms)
    seniority_hits = _seniority_hits(text, profile.seniority)
    seniority_hit = bool(seniority_hits)

    # Capped denominators avoid penalising a vacancy for unrelated CV terms,
    # while keeping the calculation reproducible and inspectable.
    keyword_den = max(1, min(12, len(_unique(profile.keywords))))
    cert_den = max(1, min(4, len(_unique(profile.certifications))))
    evidence_den = max(1, min(6, len(_unique(profile.evidence_terms))))
    components = {
        "role": 35.0 if role_hits else 0.0,
        "keywords": 25.0 * min(1.0, len(keyword_hits) / keyword_den),
        "industry": 15.0 if industry_hits else 0.0,
        "certifications": 15.0 * min(1.0, len(cert_hits) / cert_den),
        "evidence": 5.0 * min(1.0, len(evidence_hits) / evidence_den),
        "seniority": 5.0 if seniority_hit else 0.0,
    }
    percent = round(min(100.0, sum(components.values())), 1)
    return percent, {
        "profile_loaded": True,
        "components": components,
        "role_hits": role_hits,
        "keyword_hits": keyword_hits,
        "industry_hits": industry_hits,
        "certification_hits": cert_hits,
        "evidence_hits": evidence_hits,
        "seniority_match": seniority_hit,
        "seniority_hits": seniority_hits,
        "threshold_percent_non_australia": 50.0,
        "threshold_percent_australia": 20.0,
    }


def australian_role_level_allowed(title: str) -> tuple[bool, str]:
    """Keep Australia applications between Engineer and department Director."""
    value = _norm(title)
    if not value:
        return False, "missing_title"
    if re.search(r"\b(ceo|chief executive|chief [a-z ]+ officer|president|managing director|general manager)\b", value):
        return False, "above_department_director"
    if re.search(r"\b(intern|trainee|graduate|junior|assistant|technician|operator|clerk|coordinator)\b", value) and not re.search(r"\b(engineer|manager|director)\b", value):
        return False, "below_engineer"
    if not re.search(r"\b(engineer|engineering|manager|superintendent|principal|lead|director)\b", value):
        return False, "below_engineer"
    return True, "within_engineer_to_department_director"


def summarize_resume_profile(profile: ResumeProfile | None) -> dict[str, Any]:
    if profile is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "source_paths": profile.source_paths,
        "headline": profile.headline,
        "summary": profile.summary,
        "target_roles_count": len(profile.target_roles),
        "industries_count": len(profile.industries),
        "keywords_count": len(profile.keywords),
        "certifications_count": len(profile.certifications),
        "geo_preferences_count": len(profile.geo_preferences),
        "short_summary": profile.short_summary(),
    }
