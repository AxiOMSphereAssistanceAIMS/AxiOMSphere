# AIMS Multi-Agent Platform
### Industrial Project Lifecycle Automation · ISO-Aligned · On-Premise Ready

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python)](https://python.org)
[![Standards](https://img.shields.io/badge/ISO-21502%20%7C%2082079%20%7C%209001-green)](#standards)
[![DocAgent](https://img.shields.io/badge/DocAgent-Dual_Pipeline-purple)](#doc-generation-pipeline)

> **Turning raw engineering requests into ISO-compliant documents in under 10 minutes — fully automated, fully auditable.**

[🌐 Website](https://axiomsphereaassistanceaims.github.io/AIMS-Agent-Orchestrator/) · [📺 Demo Video](#demo) · [📬 Contact](#contact) · [📋 Apply for Credits](#grant-applications)

---

## One-liner

An **industrial multi-agent platform** for the launch of production projects, based on the Asset Integrity Management System (AIMS) approach (ISO 55001, ISO 55002), enables optimization of resources and timelines for pilot project deployment. The platform is designed for extension across all project lifecycle stages — from FEED through decommissioning — with further scalability to support full-cycle AIMS implementation. 

---

## The Problem

At the project justification stage, there is a critical need for empirical data, guiding documentation, and foundational decisions that will shape the project's development. These early choices can ultimately determine either the failure or the economic success of the enterprise.

In practice, organizations often proceed with launching low-budget pilot versions of projects. However, limited resources frequently result in poor-quality documentation and suboptimal outcomes. While project execution methodologies have long been established, success largely depends on how consistently and accurately teams follow clear procedural steps to build an integrated project management system.

Despite the existence of fully standardized processes, there is still no interactive system capable of supporting key specialists in real time — providing intelligent guidance and acting as a companion that can efficiently navigate extensive, widely published yet fragmented standardization sources.

**Artificial intelligence can address this gap** by serving as a network of specialized, fine-tuned agents, each designed for a specific purpose and trained on organization-specific documentation stored on corporate servers or within secure enterprise on-line platforms.

---

## Our Solution: From Hook to Factory
**Project Overview: AI-Agent Structural Integration** 
**​The Core Concept and Know-How**
​The key innovation of this project lies in its unique organizational structure and the precisely defined functional tasks assigned to individual AI agents. Each agent specializes in high-precision, niche solutions within its specific domain. Effectively, these agents execute the routine duties typically performed by human engineers, but with a guaranteed, predictable outcome. This enables their integration into a unified, task-oriented workflow that complies with the **ISO 55001** standard, ensuring that all agents operate within a synchronized system and a single structural unit, striving toward a common objective.
**​Uniqueness and Practical Foundation**
​The uniqueness of this solution is rooted in its application of real-world data from successful, existing projects. It has been developed based on the practical expertise of specialists who have a proven track record of launching complex projects.
**​Standardization and Certification**
​The framework is built upon the well-established ISO 55001 asset management standard and adheres to the **ISO 55002** guidelines. This strict alignment with international standards provides a clear roadmap for formal system certification, ensuring operational reliability and global compatibility.
​**Operational Logic of the Standard**
​The implementation of the standard follows this sequence:
​**Defining the Scope:** The process begins by establishing the "field of variation" (the operational scope).
​**Strategic Alignment:** I define the Asset Management System (AIMS) philosophy, articulate project goals with stakeholders, and delineate investment areas.
​**Functional Distribution:** Functional descriptions are assigned to departmental agents, and departmental provision documents are generated to codify these roles.
​**System Integration:** Functionality is linked via an Interface Manager Agent. Specialized "Engineer Agents" are assigned to each department to generate supporting documentation for every function.
​**Dynamic Management:** The entire ecosystem is supported by an Interface/Manager Agent whose primary task is to orchestrate functional interactions. Any modification of these interactions automatically updates the documentation for all subordinate functions.

```mermaid
graph TD
    subgraph "Phase 1 — The Hook: Engineer Assistant"
        A[Individual Engineer] -->|Natural language request| B(AI Document Assistant\nAxi Bot)
        B -->|Dual pipeline: R1-70B → Qwen-72B| C[Structured Document Draft]
        C -->|Gemini Quality Gate\nISO 45001 · ISO 21502 · IEC 82079| D{Score ≥ 80%?}
        D -->|Yes| E[✅ Approved Document .docx]
        D -->|No| F[Qwen revises with recommendations]
        F --> D
    end

    subgraph "Phase 2 — Multi-Agent Orchestration"
        E --> G{AIMS Orchestrator}
        G --> H[📊 Budget Agent]
        G --> I[⚠️ Risk & Safety Agent]
        G --> J[📋 Technical Standards Agent]
        G --> K[📁 Registry & OCR Agent]
    end

    subgraph "Phase 3 — Enterprise Hub: Bot Factory"
        H & I & J & K --> L[(Single Source of Truth\naims_registry.db)]
        L --> M[🔍 Backend Reliability Agents\nArgus Monitor]
        M --> N[🏢 On-Premise / Cloud\nCorporate Solution]
    end

    style B fill:#c084fc,stroke:#7e22ce,stroke-width:2px,color:#fff
    style E fill:#4ade80,stroke:#166534,stroke-width:2px
    style L fill:#60a5fa,stroke:#1d4ed8,stroke-width:2px
    style N fill:#34d399,stroke:#065f46,stroke-width:3px
```

---

## Live System Architecture

Our production system runs **today** with real engineers:

```mermaid
flowchart TB
    subgraph Channels
        TG[Telegram Groups\nEngineers · PM · QA]
    end

    subgraph "Agent Layer"
        Axi["Axi Bot\nExternal reasoning\nGemini API + Anthropic"]
        Omi["Omi Bot\nRegistry · OCR pipeline\nLocal Qwen 7B"]
        Argus["Argus Bot\nSystem monitor\nDevOps orchestrator"]
    end

    subgraph "Doc Generation Pipeline"
        R1["deepseek-r1:70b\nDraft generation\nDGX Spark"]
        Qwen["qwen2.5:72b\nFormatting & revision\nDGX Spark"]
        Gemini["Gemini Flash/Pro\nISO compliance scoring\n0.0 – 1.0"]
    end

    subgraph "Data Layer"
        OR[(omi_registry.db\nOCR queue)]
        AR[(aims_registry.db\nMaster documents\n+ processes)]
        TRN[(Training data\ngold_pairs.jsonl\ndpo_pairs.jsonl)]
    end

    TG --> Axi
    TG --> Omi
    Axi -->|Doc request| R1
    R1 -->|Draft| Qwen
    Qwen -->|Document| Gemini
    Gemini -->|Score + feedback| Qwen
    Qwen -->|Final .docx| TG
    Gemini -->|score≥0.8| TRN
    Omi --> AR
    OR --> AR
    Argus -.->|Monitor| Axi & Omi & R1 & Qwen
```

---

## Doc Generation Pipeline

The core AI loop — **R1 → Qwen → Gemini** — runs today on DGX Spark hardware:

| Stage | Model | Role | Avg. Time |
|-------|-------|------|-----------|
| **Draft** | deepseek-r1:70b | Structural reasoning, ISO-aware outline | ~5 min |
| **Format** | qwen2.5:72b | Professional formatting, section rewrite | ~3 min |
| **Score** | Gemini Flash/Pro | ISO compliance 0.0–1.0, gap feedback | ~15 sec |
| **Revise** | qwen2.5:72b | Targeted revision using Gemini feedback | ~2 min |

Output: production `.docx` with ≥80% ISO compliance score. If score < 0.6, pipeline retries automatically.

**Training loop baked in:** every run produces `gold_pairs.jsonl` (score ≥ 0.8) and `standard_dpo_pairs.jsonl` for continuous model fine-tuning.

---

## Standards We Align With

Our agents are natively grounded in:

| Standard | Scope |
|----------|-------|
| **ISO 21502:2020** | Project management guidance |
| **ISO 21500:2021** | Project, programme and portfolio management concepts |
| **IEC/IEEE 82079-1:2019** | Preparation of information for use — technical documentation |
| **ISO 9001 §7.5** | Control of documented information |
| **ISO 45001** | Occupational health and safety management |
| **API RP 505** | Fire protection for refineries |
| **ISO 55001:2014** | Asset management — Management systems — Requirements|
| **ISO 55002:2018** | Asset management — Management systems — Guidelines for the application of ISO 55001|

---

## Document & OCR Pipeline

```mermaid
flowchart LR
    O[📁 Outbox / Uploads] --> R[OCR Register\nomi_register.py]
    R --> ODB[(omi_registry.db)]
    ODB --> S[Sync to knowledge DB\nsync_ocr_to_aims.py]
    S --> ADB[(aims_registry.db\n✅ documents + processes)]
    ADB --> BOT[Omi Bot\n+ optional RAG]
    ADB --> AXI[Axi Bot\nSilent registry check]
```

---

## Minimal Code Example

```python
from doc_agent import DocAgent, DocGenerationRequest

agent = DocAgent()

result_path, preview, score, feedback = agent.generate(
    DocGenerationRequest(
        user_request="Create a Job Safety Analysis for confined space entry at an underground mine. "
                     "Reference ISO 45001. Include hazard table, controls hierarchy, permit conditions.",
        dual_pipeline=True,   # R1-70B → Qwen-72B → Gemini quality gate
    )
)

print(f"Document: {result_path}")
print(f"ISO compliance score: {score:.0%}")
print(f"Feedback: {feedback}")
# → Document: /data/JSA_confined_space_entry.docx
# → ISO compliance score: 84%
# → Feedback: Document covers all required JSA sections with complete hazard controls matrix.
```

---

## Use Cases

| Use Case | Document Type | Standard |
|----------|---------------|----------|
| Confined space entry | Job Safety Analysis (JSA) | ISO 45001 |
| H2S release at gas plant | Emergency Response Procedure | API RP 505 |
| Fan replacement in mine | Management of Change (MOC) | ISO 45001 §8.1.3 |
| Project kick-off | Project charter + WBS | ISO 21502 |
| Technical manual | User documentation | IEC 82079-1 |

---

## Roadmap

```mermaid
gantt
    title AIMS Platform — Phased Delivery
    dateFormat  YYYY-MM
    section Phase 1 · Foundation
    Doc registry + OCR pipeline        :done, a1, 2025-10, 6M
    Axi + Omi bots in production       :done, a2, 2026-01, 3M
    section Phase 2 · Intelligence
    Dual pipeline R1→Qwen→Gemini       :done, a3, 2026-03, 2M
    Fine-tuning loop gold+DPO          :active, a4, 2026-04, 3M
    section Phase 3 · Agent Mesh
    Budget agent                       :a5, 2026-07, 3M
    Risk & Safety agent                :a6, 2026-08, 3M
    Standards compliance agent         :a7, 2026-09, 3M
    section Phase 4 · Enterprise
    HTTP/API gateway                   :a8, 2026-10, 2M
    On-premise enterprise deployment   :a9, 2026-12, 4M
    Corporate Bot Factory launch       :a10, 2027-03, 3M
```

---

## Repository Layout

```
AIMS-Agent-Orchestrator/
├── README.md                   ← this file
├── LICENSE                     (Apache-2.0)
├── docs/
│   ├── ARCHITECTURE.md         system design details
│   ├── DEMO_SCENARIO.md        step-by-step demo guide
│   └── STANDARDS_MAPPING.md   ISO/IEC clause → agent capability
├── examples/
│   └── doc_agent_example.py   minimal usage example
└── docker-compose.yml          evaluation setup (optional)
```

---

## Grant Applications

We are seeking cloud credits / startup program support from:

| Program | Status | What we need |
|---------|--------|--------------|
| [Google for Startups Cloud Program](https://cloud.google.com/startup) | Applying | GPU compute for inference |
| [Microsoft Founders Hub](https://foundershub.startups.microsoft.com/) | Applying | Azure credits |
| [OpenAI Startup Program](https://openai.com/startups) | Applying | API credits |
| [NVIDIA Inception](https://www.nvidia.com/en-us/startups/) | Applying | DGX access / support |

**Application email template:** see [`docs/EMAILS_STARTUP_CREDITS.md`](docs/EMAILS_STARTUP_CREDITS.md)

---

## Demo

**Coming soon:** 60-second screen recording — engineer types a natural-language request → DocAgent dual pipeline → ISO-compliant `.docx` delivered to Telegram in under 10 minutes.

[📺 Watch Demo](#) · [🖼 Architecture Diagram](docs/ARCHITECTURE.md) · [🌐 Landing Page](https://axiomsphereaassistanceaims.github.io/AIMS-Agent-Orchestrator/)

---

## Contact

**Evgeny Shokk** — Founder, AIMS Platform

- 📧 Evgeny.shock@gmail.com
- 🌐 [Website](https://axiomsphereaassistanceaims.github.io/AIMS-Agent-Orchestrator/)
- 💼 [LinkedIn](https://www.linkedin.com/in/evgeny-shokk-54781716)

---

## License

[Apache License 2.0](LICENSE)

> Built on open-source: Python · Ollama · deepseek-r1 · Qwen2.5 · Google Gemini · python-telegram-bot · python-docx
