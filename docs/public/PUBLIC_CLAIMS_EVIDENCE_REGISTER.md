# AxiOMSphere — Public Claims Evidence Register

**Date:** 2026-05-23  
**Purpose:** Record evidence basis for each claim made in public-facing materials

---

## Instructions for Use

Every claim in README.md and index.html must appear in this register with its evidence basis and confidence level. Before updating public materials, add the new claim here first.

**Confidence levels:**
- `INTERNALLY_VALIDATED` — confirmed in internal development/test scenarios
- `IN_DEVELOPMENT` — actively being built, not yet validated end-to-end
- `PREPARING` — planned but not yet started externally

---

## Registered Claims

### Platform Identity

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Privacy-first multi-agent platform | README, index | Source documents processed locally; external services receive only anonymized context | INTERNALLY_VALIDATED |
| Builds and continuously improves AIMS | README, index | Multi-agent pipeline for AIMS work product drafting, review and improvement — validated internally | INTERNALLY_VALIDATED |
| Required to launch industrial projects and organise production operations | README, index | ISO 55001 positions AIMS as a management-system requirement for operating industrial assets | INTERNALLY_VALIDATED |
| ISO 55001 / ISO 55002 management-system framework basis | README, index | Platform structure follows ISO 55001 requirements and ISO 55002 guidance; stated with required disclaimer | INTERNALLY_VALIDATED |
| GFMAM Asset Management Landscape as process-framework reference | README, index | Public framework widely accepted in asset management practice; referenced, not certified | INTERNALLY_VALIDATED |

---

### Infrastructure and Architecture

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Multi-agent orchestration workflow | README, index | Agent coordination tested in internal scenarios | INTERNALLY_VALIDATED |
| Local AIMS work product drafting without external source transmission | README, index | Source documents processed on private GPU; only anonymized context sent externally | INTERNALLY_VALIDATED |
| OCR and AIMS document registry pipeline | README, index | OCR ingestion operational; Qdrant registry running | INTERNALLY_VALIDATED |
| Evidence and learning-case collection | README, index | Gold pair and DPO pair auto-save operational | INTERNALLY_VALIDATED |
| Private GPU infrastructure | README, index | DGX Spark hardware in private environment | INTERNALLY_VALIDATED |
| Docker, Redis, Qdrant, Python stack | README | Stack confirmed operational | INTERNALLY_VALIDATED |
| Local open-weight language models via Ollama | README | Ollama serving local models confirmed | INTERNALLY_VALIDATED |
| Vector search for AIMS document retrieval | README | Qdrant operational | INTERNALLY_VALIDATED |
| Prometheus and Grafana monitoring | README | Monitoring stack deployed | INTERNALLY_VALIDATED |

---

### Workflow Capabilities

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| AIMS work product drafting and review workflow | README, index | Implemented and run in internal test scenarios | INTERNALLY_VALIDATED |
| ISO 55001 / ISO 55002-aligned structure | README, index | Work products developed within management-system framework | INTERNALLY_VALIDATED |
| Controlled external evaluation (anonymized context only) | README, index | Architecture design implemented; external evaluation controlled | INTERNALLY_VALIDATED |
| Human review required before operational use | README, index | Policy constraint; no automatic certification claimed | INTERNALLY_VALIDATED |
| AIMS framework benchmarking against standards and guidance | README, index | Benchmarking pipeline in active development | IN_DEVELOPMENT |

---

### AIMS Lifecycle Stages

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Stage 01: Project Definition work products | README, index | Work product categories established from ISO 55001 / ISO 55002 requirements | INTERNALLY_VALIDATED |
| Stage 02: Organisational Setup work products | README, index | Work product categories established from ISO 55001 / ISO 55002 requirements | INTERNALLY_VALIDATED |
| Stage 03: Functional Framework work products | README, index | Core AIMS process documentation tested in internal scenarios | INTERNALLY_VALIDATED |
| Stage 04: Operational Readiness work products | README, index | Work product categories established from management-system requirements | IN_DEVELOPMENT |
| Stage 05: Production Operations work products | README, index | Continuous improvement and management review structure defined | IN_DEVELOPMENT |

---

### Development-Stage Capacity Model

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| 350 workflow hours / ~2 working months for 1,000 AIMS work products | README, index | Estimate based on ~10 min human task formulation + ~11 min agent-assisted preparation per item; 8-hr day / 22-day month; stated as development-stage estimate subject to validation | IN_DEVELOPMENT |
| Estimate excludes qualified review, approval and assurance | README, index | Explicit qualification included in all instances of this claim | INTERNALLY_VALIDATED |
| Subject to pilot validation | README, index | Explicit qualification included in all instances of this claim | INTERNALLY_VALIDATED |

---

### Development Status

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Platform is in active development | README, index | Codebase under active development | INTERNALLY_VALIDATED |
| Preparing for external industrial pilot | README, index | No external pilot yet completed | PREPARING |
| 90-day validation plan | README, index | Plan documented internally | IN_DEVELOPMENT |

---

### Founder and Differentiation Claims (Added 2026-05-23 — Final Grant-Ready Revision)

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Founder: Evgeny Shokk | README, narrative, one-pager, website | Name confirmed in all project materials; single accountable founder-operator | INTERNALLY_VALIDATED |
| AIMS-centred scope (not general document tool) | README, index, narrative | Platform architecture designed exclusively around AIMS work-product types; agents, knowledge layer, and benchmarks all AIMS-specific | INTERNALLY_VALIDATED |
| Private by default — architectural design, not configuration | README, index, narrative | Source documents processed locally on private GPU; external path requires explicit anonymization and authorisation steps; design constraint, not option | INTERNALLY_VALIDATED |
| Coordinated agents across full AIMS framework | README, index | Multiple specialised agents (generation, review, registry, retrieval) coordinated via orchestration layer | INTERNALLY_VALIDATED |
| Framework-grounded — ISO 55001 requirements and ISO 55002 guidance | README, index, narrative | Work products aligned to management-system requirements; disclaimer present | INTERNALLY_VALIDATED |

---

### Validation Roadmap Claims (Added 2026-05-23 — Final Grant-Ready Revision)

| Claim | Location | Status |
|-------|----------|--------|
| Multi-agent orchestration and work-product pipeline completed | README, index | INTERNALLY_VALIDATED |
| Privacy architecture (local inference + controlled external) completed | README, index | INTERNALLY_VALIDATED |
| OCR ingestion, document registry and evidence retention completed | README, index | INTERNALLY_VALIDATED |
| ISO 55001 / ISO 55002 scope expansion and benchmarking pipeline in development | README, index | IN_DEVELOPMENT |
| Controlled industrial pilot preparing (credits enable this) | README, index | PREPARING |

---

### Path to Pilot Claims (Added 2026-05-23 — Final Grant-Ready Revision)

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Staged pathway from internal validation to controlled external pilot | README, index, narrative, one-pager | Logical development sequence; no external customers or signed deployments claimed | INTERNALLY_VALIDATED |
| Stage 1 requires credits | narrative, index | External benchmark evaluation requires API access not available locally | INTERNALLY_VALIDATED |
| No external customers or signed deployments at this stage | README, index | Explicit statement included in all pathway descriptions | INTERNALLY_VALIDATED |

---

## Claims Removed in Grant-Readiness Rewrite (2026-05-23)

The following claims appeared in the original repository and were removed for the grant-readiness version:

| Removed claim | Reason |
|--------------|--------|
| "ISO-compliant" / "ISO compliance score" | Cannot certify compliance; outputs require qualified review |
| "production-ready" / "currently working in production" | Platform in active development |
| "under 10 minutes" | Unverified external performance claim |
| "1000 documents processed" | Unverified external claim |
| "1.5 years" / "1,5 year" | Marketing claim not appropriate for technical documentation |
| "14 days" | Unverified timeline claim |
| Specific model names (Gemini, Nemotron, DeepSeek) | Third-party competitive sensitivity |
| Internal port numbers (8000, 8082, etc.) | Internal infrastructure — not for public |
| ".env", "API_KEY", "TOKEN" references | Security — not for public |

---

## Scope Restoration (2026-05-23)

The grant-readiness rewrite narrowed the product scope to "engineering document workflows." The following scope items have been restored with appropriate qualifications:

| Restored scope element | Qualification included |
|-----------------------|----------------------|
| ISO 55001 / ISO 55002 as management-system foundation | "follows as framework basis"; disclaimer that outputs do not constitute certification |
| Full AIMS lifecycle (5 stages) | "development-stage"; staged capabilities qualify which are validated vs in development |
| Capacity model (350 hr / 1,000 items) | Full development-stage qualification; excludes review/approval/assurance |
| GFMAM Landscape reference | Referenced as process-framework; not certified compliance |
| Brand pillars (Axiom / AIMS / O&M / Sphere) | Descriptive; not performance claims |

---

*This register is maintained as a living document. Add new claims before publishing.*
