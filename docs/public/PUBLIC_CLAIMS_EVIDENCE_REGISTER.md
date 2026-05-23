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

### Infrastructure and Architecture

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Multi-agent orchestration workflow | README, index | Agent coordination tested in internal scenarios | INTERNALLY_VALIDATED |
| Local document drafting without external source transmission | README, index | Source documents processed on private GPU; only anonymized context sent externally | INTERNALLY_VALIDATED |
| OCR and document registry pipeline | README | OCR ingestion operational; Qdrant registry running | INTERNALLY_VALIDATED |
| Evidence and learning-case collection | README | Gold pair and DPO pair auto-save operational | INTERNALLY_VALIDATED |
| Private GPU infrastructure | README | DGX Spark hardware in private environment | INTERNALLY_VALIDATED |
| Docker, Redis, Qdrant, Python stack | README | Stack confirmed operational | INTERNALLY_VALIDATED |
| Local open-weight language models | README | Ollama serving local models confirmed | INTERNALLY_VALIDATED |
| Vector search for document retrieval | README | Qdrant operational | INTERNALLY_VALIDATED |
| Prometheus and Grafana monitoring | README | Monitoring stack deployed | INTERNALLY_VALIDATED |

---

### Workflow Capabilities

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Document drafting and review workflow | README, index | Implemented and run in internal test scenarios | INTERNALLY_VALIDATED |
| Source-backed review against standards and guidance themes | README, index | Benchmarking pipeline in active development | IN_DEVELOPMENT |
| Controlled external evaluation (anonymized context only) | README, index | Architecture design implemented; external evaluation controlled | INTERNALLY_VALIDATED |
| Human review required before operational use | README, index | Policy constraint; no automatic certification claimed | INTERNALLY_VALIDATED |

---

### Use Cases

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Asset preservation procedure drafting | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |
| Shutdown and de-preservation documentation | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |
| Maintenance and reliability workflows | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |
| Technical procedure review | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |
| Engineering checklist preparation | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |
| Asset management documentation | README, index | Tested in internal scenarios | INTERNALLY_VALIDATED |

---

### Development Status

| Claim | Location | Evidence basis | Confidence |
|-------|----------|---------------|------------|
| Platform is in active development | README, index | Codebase under active development | INTERNALLY_VALIDATED |
| Preparing for external industrial pilot | README, index | No external pilot yet completed | PREPARING |
| 90-day validation plan | README, index | Plan documented internally | IN_DEVELOPMENT |

---

## Claims Removed

The following claims appeared in earlier versions and were removed:

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

*This register is maintained as a living document. Add new claims before publishing.*
