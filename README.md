# AxiOMSphere

> Privacy-first industrial AI for AIMS work-product development and review, evolving toward controlled knowledge, orchestration and project-support capabilities.

[![Website](https://img.shields.io/badge/website-axiomsphereai.com-7c3aed)](https://axiomsphereai.com)
[![Demo](https://img.shields.io/badge/demo-watch-06b6d4)](#demo)
[![Contact](https://img.shields.io/badge/contact-hello%40axiomsphereai.com-10b981)](mailto:hello@axiomsphereai.com)

---

## What AxiOMSphere Is

AxiOMSphere is a development-stage AI system for industrial Asset Integrity Management. It provides AI-assisted creation, review, and traceability of AIMS work products — running on private infrastructure. Project source documents remain private; authorised external evaluation uses only anonymised or de-identified context for structure and framework-alignment assessment.

The system is built on coordinated LLM agents, each responsible for a specific function in the document pipeline. All generated outputs require human expert review and approval before use.

---

## Current Applied Stage

**M1: AI-Assisted AIMS Work-Product Development and Review**

What is validated and operating today in our development environment:

- **Draft generation** — engineer submits a plain-language request via Telegram; system generates a structured AIMS work-product draft aligned to the applicable ISO standard
- **Framework-alignment review** — every draft is reviewed against applicable ISO 55001 requirements and ISO 55002 guidance; gaps identified, revision guidance generated
- **Structured revision loop** — draft → review → revise → re-review; outputs progress through multiple passes; human review and approval required before use
- **Document registry** — accepted documents registered in a local registry with generation metadata (revision count, timestamp, review record)
- **Privacy-first infrastructure** — runs on private GPU infrastructure; all document content stays on-premise; no project data transmitted to external services during draft generation
- **Evidence retention** — validated outputs are retained as structured evidence to support future controlled improvement cycles (M2 development objective)

Representative work-product types: safety procedures, management-of-change documentation, technical work products and AIMS registers — structured according to applicable standards requirements.

---

## Why This Initial Stage Matters

The problem we are solving is not about generation speed. It is about access and consistency.

At the project justification stage, organizations need empirical data, guiding documentation, and foundational decisions that shape the entire project lifecycle. In practice, limited resources produce poor-quality documentation and suboptimal outcomes — even when the methodologies are fully standardized.

AI-assisted work-product development addresses this by providing structured, standards-aligned drafts that engineers can review, correct, and approve — reducing the time required to produce compliant initial documentation while keeping humans in control of every output.

The privacy-first, on-premise deployment model is a deliberate design choice: AIMS documentation contains sensitive operational and safety information that organizations cannot and should not route through external services.

---

## Website and Demo

**Live site:** [axiomsphereai.com](https://axiomsphereai.com)

The website includes a walkthrough demo of the current applied stage — AI-assisted AIMS work-product development via Telegram bot interface. The demo shows the development-stage workflow. All outputs require human expert review before operational use.

---

## Development Roadmap

Six milestones from current applied stage to long-term platform vision, sequenced by technical dependency and operational readiness:

| Milestone | Capability | Status |
|-----------|-----------|--------|
| **M1** | AI-Assisted Work-Product Development & Review | **Current** |
| **M2** | Controlled Knowledge & Self-Learning | In Development |
| **M3** | Self-Repair & Resilience | Planned |
| **M4** | Multi-Agent Orchestration | Planned |
| **M5** | Client-Facing AIMS Assistant | Future |
| **M6** | AIMS-Guided Project Development Support | Long-Term Vision |

**M2 (In Development):** OCR ingestion of approved documents into a vector knowledge base. RAG-augmented generation from organization-specific precedents. Nightly fine-tuning on approved outputs.

**M3 (Planned):** Automated fault detection and repair loop across the agent pipeline. Self-healing infrastructure with human confirmation gate before applying fixes.

**M4 (Planned):** Coordinated specialist agents (safety, budget, procurement, standards) sharing a single document registry and knowledge base. Cross-discipline consistency enforcement.

**M5 (Future):** Interactive assistant for engineering teams — query project history, identify document gaps, surface regulatory requirements, support audit preparation.

**M6 (Long-Term Vision):** Platform-level support for full project lifecycle — from justification through commissioning.

---

## Long-Term Platform Vision

The long-term value of AxiOMSphere is not document generation speed — it is accumulated project understanding.

An assistant that has ingested all documents created during a project's lifecycle, knows the decisions made at each stage, understands the connections between departments, and can help teams reduce duplication, improve resource use, and maintain continuity across personnel changes.

This is not a current capability. It is the direction our staged development roadmap is building toward — one validated milestone at a time.

---

## Privacy-First and Human-Review Boundary

**What stays private:**
- All document content is processed on-premise on private GPU infrastructure
- No project data is sent to external services during draft generation
- External evaluation service access is optional and configurable; only anonymised, context-limited prompts are sent, not full document content

**Human review boundary:**
- Every generated document requires engineer review and approval before operational use
- The system does not make autonomous decisions about document acceptance in safety-critical contexts
- The registry records who approved each document and when

---

## ISO 55001 / 55002 / GFMAM Reference

The AIMS work-product pipeline is structured around:

- **ISO 55001:2024** — Asset management: requirements
- **ISO 55002:2018** — Asset management: guidelines for the application of ISO 55001
- **GFMAM Asset Management Landscape** — 39 subjects across 6 subject groups

All generated outputs require qualified human review against applicable standards before operational use.

---

## Why Startup Credits Are Needed Now

AxiOMSphere is at the compute-intensive transition from M1 to M2. The bottlenecks that credits would directly address:

- **GPU compute** — pipeline validation and M2 model improvement cycles require sustained private GPU capacity beyond current development allocation
- **Vector infrastructure** — M2 controlled knowledge layer requires a persistent, high-recall vector retrieval service; scaling beyond the development dataset requires additional infrastructure
- **Evaluation API credits** — framework-alignment review currently runs at development-tier rate limits; full-stack validation requires higher quota
- **Repair and review automation** — used for bounded repair and controlled review automation; current usage is manually throttled due to cost constraints

We are applying to: Google for Startups Cloud, Microsoft Founders Hub, NVIDIA Inception, Anthropic Credits.

---

## Contact

**Email:** [hello@axiomsphereai.com](mailto:hello@axiomsphereai.com)

**GitHub:** [AxiOMSphereAssistanceAIMS/AxiOMSphere](https://github.com/AxiOMSphereAssistanceAIMS/AxiOMSphere)

**LinkedIn:** [Evgeny Shokk](https://www.linkedin.com/in/evgeny-shokk-54781716)

For startup credit applications, partnership inquiries, or research collaboration — please reach out directly at hello@axiomsphereai.com.

---

*Apache-2.0 License · Development stage — not for production use without engineering review*
