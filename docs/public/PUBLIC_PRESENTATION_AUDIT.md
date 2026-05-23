# AxiOMSphere — Public Presentation Audit

**Date:** 2026-05-23  
**Scope:** README.md, index.html, landing/index.html  
**Purpose:** Pre-publication compliance review for startup credit applications

---

## Audit Checklist

### Safety and Privacy Statements

| Statement | README.md | index.html | landing/index.html |
|-----------|-----------|------------|--------------------|
| Safety notice (human review required) | ✅ Present | ✅ Present | ✅ Present |
| Privacy notice (sensitive documents stay local) | ✅ Present | ✅ Present | ✅ Present |

---

### Removed Claims

The following categories of claims were removed from all public-facing files:

| Category | Examples removed | Reason |
|----------|-----------------|--------|
| Compliance certification language | "ISO-compliant", "ISO compliance score", "certified compliance" | Cannot certify compliance — outputs require qualified review |
| Production status overclaims | "production-ready", "currently working in production" | Platform is in active development / internal testing |
| Specific performance metrics | "under 10 minutes", "14 days", "1000 documents processed" | Unverified external claims |
| Internal infrastructure details | Port numbers, model names, API keys, internal service endpoints | Not appropriate for public presentation |
| Third-party model names | Gemini, Nemotron, DeepSeek | Competitive sensitivity and licence references |

---

### Retained Claims

All retained claims reflect internally validated status:

| Claim | Evidence basis |
|-------|---------------|
| Multi-agent orchestration workflow — Internally validated | Internal agent coordination confirmed operational |
| Document drafting and review workflow — Implemented for internal test scenarios | Internal test scenarios exist and have been run |
| OCR and document registry pipeline — Implemented | OCR ingestion and Qdrant registry operational |
| Evidence and learning-case collection — Implemented in development workflow | Gold pair and DPO pair auto-save confirmed |
| Standards and guidance benchmarking — In active development | Benchmarking pipeline under development |
| External industrial pilot — Preparing | No external pilot has been completed |

---

### Contact and Links

| Item | Value | Status |
|------|-------|--------|
| Primary contact | hello@axiomsphereai.com | ✅ Correct |
| GitHub link | https://github.com/AxiOMSphereAssistanceAIMS/AxiOMSphere | ✅ Present |
| Website link | https://axiomsphereassistanceaims.github.io/AxiOMSphere/ | ✅ Present |
| Telegram bot link | Removed | ✅ Removed |

---

### Banned Terms Scan

The following terms were confirmed absent from all public files:

- ISO-compliant, ISO compliance verified, ISO compliance score, full compliance, certified compliance
- currently working in production, production today
- 1.5 years, 1,5 year, 1000 documents, 14 days
- Gemini, Nemotron, DeepSeek
- slot120, API_KEY, TOKEN, PASSWORD
- Port numbers: 8000, 8765, 8767, 20129, 8082
- .env references

---

## Deployment Verification

The following external surfaces were verified by live HTTP request on 2026-05-23.

### GitHub Pages — https://axiomsphereassistanceaims.github.io/AxiOMSphere/

| Check | Result |
|-------|--------|
| Pages source branch | main (root `/`) |
| Pages build type | legacy |
| Pages status | built |
| Commit deployed | 1b909d0 — docs: prepare public site and README for startup credit applications |
| Title element | `AxiOMSphere — Privacy-first Industrial AI` ✅ |
| Hero text | "Privacy-first industrial AI for engineering document workflows" ✅ |
| Safety statement | present ✅ |
| Privacy statement | present ✅ |
| Contact | hello@axiomsphereai.com ✅ |

**Old content confirmed absent from live site:**

| Banned term | Live site |
|-------------|-----------|
| ISO-compliant | ABSENT ✅ |
| ISO Compliance Score | ABSENT ✅ |
| deepseek-r1 | ABSENT ✅ |
| qwen2.5:72b | ABSENT ✅ |
| Gemini Flash | ABSENT ✅ |
| under 10 minutes | ABSENT ✅ |
| 1,5 year | ABSENT ✅ |
| currently working in production | ABSENT ✅ |

### Public README — https://raw.githubusercontent.com/AxiOMSphereAssistanceAIMS/AxiOMSphere/main/README.md

| Check | Result |
|-------|--------|
| Default branch | main |
| Size | 154 lines / 7117 bytes |
| Opening line | "Privacy-first industrial AI for source-backed engineering document workflows." ✅ |
| Safety statement | present ✅ |
| ISO compliance verified | ABSENT ✅ |
| currently working in production | ABSENT ✅ |
| 1,5 year | ABSENT ✅ |
| Gemini | ABSENT ✅ |

### Root Cause of Earlier Mismatch

The previous session wrote `README.md` and `index.html` to the local clone at `/tmp/axiomsphere-public/` but the conversation context ran out before the `git commit` and `git push` were executed. The user's external verification was done during this window — the files were correct on disk but had not yet been pushed to GitHub. The commit and push were completed at the start of the following session.

**Note:** There is also an `origin/master` branch on the repository containing old content. This branch does not affect the public README display (default branch is `main`) or GitHub Pages (source branch is `main`), but it should be deleted or updated to avoid confusion.

---

## Audit Outcome

**Result: PASS — externally verified on 2026-05-23.**

| Surface | Status |
|---------|--------|
| Live GitHub Pages (index.html) | ✅ VERIFIED — new privacy-first content live |
| Public README (main branch) | ✅ VERIFIED — no banned terms present |
| landing/index.html | ✅ VERIFIED — same content as index.html |
| docs/public/ support documents | ✅ CREATED — audit, evidence register, narrative |

All public-facing claims are either:
- Internally validated and stated conservatively, or
- Framed as "in development" / "preparing"

No compliance certifications, production claims, or internal infrastructure details remain in any deployed public surface.

---

*This audit was performed as part of the public grant readiness preparation for AxiOMSphere.*
