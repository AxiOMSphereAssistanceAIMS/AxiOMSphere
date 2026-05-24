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

### Target Capability Architecture — Per-Layer Status Claims (Added 2026-05-24 — Staged Narrative Alignment)

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Layer 1 — Project Development (AIMS work-product generation, review and registration): Current Applied Capability | index, one-pager, narrative | Implemented and run in internal development and test scenarios | INTERNALLY_VALIDATED |
| Layer 2 — Master Knowledge and Document Base (AIMS Single Source of Truth): Current Applied Capability | index, one-pager, narrative | OCR ingestion, Qdrant registry, and evidence retention operational | INTERNALLY_VALIDATED |
| Layer 3 — Orchestration and Synchronisation (interface alignment and gap resolution): In Development | index, one-pager, narrative | Architecture designed; components in active development; not yet validated end-to-end | IN_DEVELOPMENT |
| Layer 4 — Execution Control and Feedback (quality thresholds and human review gates): In Development | index, one-pager, narrative | Quality thresholds and gate logic in active development | IN_DEVELOPMENT |
| Layer 5 — Learning and Training (continuous fine-tuning from validated outputs): In Development | index, one-pager, narrative | Fine-tuning pipeline operational for internal model; continuous loop in development | IN_DEVELOPMENT |
| Layer 6 — Recovery and Repair (failure detection and targeted automated repair): In Development | index, one-pager, narrative | Monitoring and repair architecture in active development | IN_DEVELOPMENT |
| Layer 7 — Security, Policy and Oversight (access controls and change management gates): Planned | index, one-pager, narrative | Planned; not yet started | PREPARING |
| Layer 8 — Resilience and Redundancy (dual-node routing and failover logic): Planned | index, one-pager, narrative | Planned; not yet started | PREPARING |

---

### Six-Milestone Staged Roadmap Claims (Added 2026-05-24 — Staged Narrative Alignment)

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| M1 — Current Applied Capability (work-product drafting, review, registration): Completed | index | Layers 1–2 validated in internal development scenarios | INTERNALLY_VALIDATED |
| M2 — Learning Loop (benchmarking pipeline, continuous fine-tuning): In Development | index | Pipeline architecture in active development; not yet validated end-to-end | IN_DEVELOPMENT |
| M3 — Repair and Recovery (infrastructure monitoring, diagnosis, targeted repair): In Architecture | index | Architecture designed; implementation in early development | IN_DEVELOPMENT |
| M4 — Orchestration at Scale (framework synchronisation, change-impact tracing): Planned | index | Planned following M2 and M3; not yet started | PREPARING |
| M5 — Client-Facing Support (controlled pilot with qualified industrial partner): Future | index | Follows successful M1–M4 completion; no external customers or signed deployments | PREPARING |
| M6 — AIMS-Guided Industrial Platform (long-term vision): Long-Term Vision | index | Long-term design intent; explicitly not a current product offering | PREPARING |

---

### Path to Pilot Claims (Added 2026-05-23 — Final Grant-Ready Revision)

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Staged pathway from internal validation to controlled external pilot | README, index, narrative, one-pager | Logical development sequence; no external customers or signed deployments claimed | INTERNALLY_VALIDATED |
| Stage 1 requires credits | narrative, index | External benchmark evaluation requires API access not available locally | INTERNALLY_VALIDATED |
| No external customers or signed deployments at this stage | README, index | Explicit statement included in all pathway descriptions | INTERNALLY_VALIDATED |

---

## Claims Removed or Updated in Staged Narrative Alignment (2026-05-24)

The following claims were present in public materials prior to the staged narrative alignment and have been updated or removed:

| Updated/Removed claim | Change made | Reason |
|----------------------|------------|--------|
| "Full-stack, closed-loop industrial AI platform" | Removed as current-state label | Platform is development-stage; closed-loop is a design intent, not validated delivery |
| "Build, synchronise, restore and continuously improve" as current delivery | Removed from all instances | These capabilities span Layers 3–8 which are In Development or Planned, not current applied capability |
| "24-hour review cycle" as planning target in public materials | Removed from all public-facing files | Unvalidated performance target; inappropriate for public claims without controlled validation data |
| Capacity model (1,000 items / 350 hours) as "Planning Scenario" | Relabelled "Illustrative comparison only — not a delivery commitment or measured product performance" | Clearer qualification to prevent misreading as a delivery commitment |
| "All eight architecture layers completed/validated" | Updated to per-layer status (Layers 1–2: Current Applied; Layers 3–6: In Development; Layers 7–8: Planned) | Accurate per-layer status representation |
| 5-milestone roadmap (completed/preparing/in dev framing) | Replaced with 6-milestone staged roadmap M1–M6 with explicit stage labels | Clearer staged progression from current applied capability to long-term vision |

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
