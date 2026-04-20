# AxiOMSphere Facility
> **Multi-Agent Platform for Integrated Asset Integrity & O&M Lifecycle Orchestration**

## 🧩 Project Nomenclature
The name **AxiOMSphere** is a strategic integration of our core technological pillars:

* **Axiom**: Representing the foundational, self-evident precision of international standards.
* **AIMS**: **A**sset **I**ntegrity **M**anagement **S**ystem — the central intelligence core.
* **O&M**: **O**peration & **M**aintenance — focusing on the high-value phase of the industrial lifecycle.
* **Sphere**: A unified, 360-degree multi-agent ecosystem ensuring a "Single Source of Truth".

---

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

**The Core Concept and Know-How**
The key innovation of this project lies in its unique organizational structure and the precisely defined functional tasks assigned to individual AI agents. Each agent specializes in high-precision, niche solutions within its specific domain. Effectively, these agents execute the routine duties typically performed by human engineers, but with a guaranteed, predictable outcome. This enables their integration into a unified, task-oriented workflow that complies with the **ISO 55001** standard, ensuring that all agents operate within a synchronized system and a single structural unit, striving toward a common objective.

**Uniqueness and Practical Foundation**
The uniqueness of this solution is rooted in its application of real-world data from successful, existing projects. It has been developed based on the practical expertise of specialists who have a proven track record of launching complex projects.

**Standardization and Certification**
The framework is built upon the well-established ISO 55001 asset management standard and adheres to the **ISO 55002** guidelines. This strict alignment with international standards provides a clear roadmap for formal system certification, ensuring operational reliability and global compatibility.

**Operational Logic of the Standard**
The implementation of the standard follows this sequence:

**Defining the Scope:** The process begins by establishing the "field of variation" (the operational scope).

**Strategic Alignment:** Define the Asset Management System (AIMS) philosophy, articulate project goals with stakeholders, and delineate investment areas.

**Functional Distribution:** Functional descriptions are assigned to departmental agents, and departmental provision documents are generated to codify these roles.

**System Integration:** Functionality is linked via an Interface Manager Agent. Specialized "Engineer Agents" are assigned to each department to generate supporting documentation for every function.

**Dynamic Management:** The entire ecosystem is supported by an Interface/Manager Agent whose primary task is to orchestrate functional interactions. Any modification of these interactions automatically updates the documentation for all subordinate functions.

---

## 🏗 Factory Architecture & Development Roadmap
The project evolves through a hierarchical deployment of specialized agents, ensuring that operational execution always follows strategic integrity.

---

### Diagram 1 — AxiOMSphere Agent Type Registry

> 7 universal agent types deployed across all departments of any Plant Project.
> Each type runs in parallel instances within different functional domains simultaneously.

```mermaid
flowchart TD
    HEADER["🏭 AxiOMSphere Facility — Agent Type Registry\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nAxi · Asset Integrity Management · Operations & Maintenance · Sphere"]

    HEADER --> T1 & T2 & T3 & T4 & T5 & T6 & T7

    T1["📄 DocAgent\n━━━━━━━━━━━━━━━━━\nAxi Bot\n─────────────────\nCorporate document generation\nfor AIMS launch & operations\nPipeline: R1-70B → Qwen-72B\n→ Gemini ISO scoring ≥ 80%\n─────────────────\n⚡ Parallel per department\n✅ Production"]

    T2["🗄️ DBAgent\n━━━━━━━━━━━━━━━━━\nOmi Bot\n─────────────────\nDocument archive · OCR pipeline\nRAG semantic memory layer\nSingle Source of Truth\naims_registry.db\n─────────────────\n🔄 Always active\n✅ Production + Extend"]

    T3["📊 SysDog\n━━━━━━━━━━━━━━━━━\nArgus Bot\n─────────────────\nKPI collection & monitoring\nScheduler · Queue orchestration\nCyclic maintenance plans\nFailure analysis · Model tuning\nTraining loop supervision\n─────────────────\n🔄 Continuous\n✅ Production"]

    T4["🧠 SysLogicArh\n━━━━━━━━━━━━━━━━━\n─────────────────\nLogic & synchronization\nCross-dept AIMS alignment\nFunctional interface mapping\nSAMP adherence verification\nDept ↔ Dept coherence\n─────────────────\n⚡ Parallel per process\n🔜 Next deploy"]

    T5["🔐 SysPolic\n━━━━━━━━━━━━━━━━━\n─────────────────\nAccess rights & permissions\nDocument ownership registry\nMoC control & registration\nSecurity policy enforcement\nModification gate keeper\n─────────────────\n🔒 Blocking gate\n🔜 Next deploy"]

    T6["🔧 SysMR\n━━━━━━━━━━━━━━━━━\n─────────────────\nReceives ready repair scripts\nfrom SysDog analysis\nExecutes code fixes & patches\nSystem file modifications\nScheduled maintenance tasks\nRequires SysPolic approval\n─────────────────\n⚡ Scheduled / on-demand\n🔜 Next deploy"]

    T7["🔍 SysRAG\n━━━━━━━━━━━━━━━━━\n─────────────────\nSemantic search layer\nContext provider for all agents\nVector index over aims_registry\nInter-agent knowledge requests\nEmbedding: nomic / BGE\n─────────────────\n🔄 Background / on-demand\n🔜 Integrate into DBAgent"]

    style HEADER fill:#0d1117,stroke:#58a6ff,color:#e6edf3
```

---

### Diagram 2 — Plant Project Development Sequence
#### From General to Specific · ISO 55001:2024 / ISO 55002:2018

> Sequence verified against ISO 55001 clause structure:
> §4 Context → §5 Leadership → §6 Planning → §7 Support → §8 Operation → §9 Evaluation → §10 Improvement

```mermaid
flowchart TD
    START(["🏗️ PLANT PROJECT START\nGreenfield / New Enterprise"])

    START --> S0

    subgraph S0["📋 Stage 0 — TEJ: Technical-Economic Justification\n(ISO 55001 §4.1 · §4.2 — Organizational Context & Stakeholders)"]
        direction LR
        S0A["Feasibility study\n& business case"] --> S0B["Stakeholder identification\n& requirements (ISO §4.2)"] --> S0C["Define AMS scope\n& field of variation (ISO §4.3)"]
    end

    S0 --> S1

    subgraph S1["🎯 Stage 1 — FEED: Front-End Engineering & Design\n(ISO 55001 §5 Leadership · §6 Planning)"]
        direction LR
        S1A["AIMS Philosophy &\nAsset Mgmt Policy (§5.2)"] --> S1B["SAMP Development\nStrategic Asset Mgmt Plan (§6.2)"] --> S1C["Risk & Opportunity\nFramework (§6.1)"] --> S1D["Organizational structure\nRoles & RACI (§5.3)"]
    end

    S1 --> S2

    subgraph S2["🔍 Stage 2 — DD: Due Diligence\n(ISO 55001 §7 Support · §6.1 Risk)"]
        direction LR
        S2A["Asset inventory\n& criticality assessment"] --> S2B["Gap analysis vs\nISO 55001 requirements"] --> S2C["Competency assessment\n& training plan (§7.2)"] --> S2D["Data standards &\nownership (§7.5)"]
    end

    S2 --> S3

    subgraph S3["⚙️ Stage 3 — EPC: Engineering, Procurement & Construction\n(ISO 55001 §8.1 Operational Planning · §8.3 Outsourcing)"]
        direction LR
        S3A["Design integrity &\nverification (§8.1)"] --> S3B["Procurement control\n& supplier qualification"] --> S3C["Construction quality\n& documentation control (§7.5)"] --> S3D["Asset register build\n& tagging"]
    end

    S3 --> S4

    subgraph S4["🚀 Stage 4 — PO: Pre-Operations / Commissioning\n(ISO 55001 §8.2 Asset Mgmt Plans · §8.4 Change Mgmt)"]
        direction LR
        S4A["Asset management plans\nper asset class (§8.2)"] --> S4B["SOP development\n& approval"] --> S4C["MoC process activation\n(§8.4)"] --> S4D["Pre-startup safety review\n& permit system"]
    end

    S4 --> S5

    subgraph S5["🏭 Stage 5 — O&M: Operations & Maintenance\n(ISO 55001 §8 Operation · §9 Performance Evaluation)"]
        direction LR
        S5A["Operational control\n& monitoring (§8.1)"] --> S5B["Preventive & predictive\nmaintenance strategies"] --> S5C["RBI · NDT · Inspection\nplanning (Risk-based)"] --> S5D["KPI tracking &\nperformance review (§9.1)"]
    end

    S5 --> S6

    subgraph S6["📈 Stage 6 — Continuous Improvement\n(ISO 55001 §9 Evaluation · §10 Improvement)"]
        direction LR
        S6A["Internal & external audits\nISO 55001 compliance (§9.2)"] --> S6B["Incident investigation\nRCA & lessons learned (§10.1)"] --> S6C["Management review\n& SAMP update (§9.3)"] --> S6D["ISO 55001 Certification\n& recertification cycle"]
    end

    S6 --> S7

    subgraph S7["🔚 Stage 7 — Decommissioning\n(ISO 55001 §8.1 · Full lifecycle closure)"]
        direction LR
        S7A["Asset disposal\nplanning & execution"] --> S7B["Knowledge transfer\n& archive closure"] --> S7C["Regulatory compliance\n& environmental closeout"]
    end

    S7 --> DONE(["✅ FULL LIFECYCLE COMPLETE\nISO 55001 Certified AIMS"])

    S6 -.->|"PDCA Loop · Plan → Do → Check → Act"| S1
```

---

### Diagram 3 — Agent Deployment Matrix: AxiOMSphere × Plant Project Lifecycle

> Which agent types are active at each stage. Agents combine and run in parallel within each stage.
> SysLogicArh acts as Interface Manager — active across all stages simultaneously.

```mermaid
flowchart LR
    subgraph LEGEND["Legend"]
        L1["🟢 Active / Core"]
        L2["🟡 Partial / Advisory"]
        L3["⚫ Not applicable"]
    end

    subgraph TEJ["Stage 0 · TEJ"]
        TEJ1["📄 DocAgent\nFeasibility docs\nBusiness case 🟢"]
        TEJ2["🗄️ DBAgent\nRegistry init\nDoc archive 🟢"]
        TEJ3["📊 SysDog\nBaseline KPI\ndefinition 🟡"]
        TEJ4["🧠 SysLogicArh\nScope mapping\nStakeholder logic 🟢"]
        TEJ5["🔐 SysPolic\nInitial rights\n& ownership 🟢"]
        TEJ6["🔧 SysMR\n— ⚫"]
        TEJ7["🔍 SysRAG\nISO knowledge\nbase index 🟢"]
    end

    subgraph FEED["Stage 1 · FEED"]
        FEED1["📄 DocAgent\nSAMP · Policy\nObjectives docs 🟢"]
        FEED2["🗄️ DBAgent\nSAMP storage\nVersion control 🟢"]
        FEED3["📊 SysDog\nKPI framework\nReporting setup 🟢"]
        FEED4["🧠 SysLogicArh\nDept alignment\nFunctional sync 🟢"]
        FEED5["🔐 SysPolic\nMoC framework\nApproval matrix 🟢"]
        FEED6["🔧 SysMR\n— ⚫"]
        FEED7["🔍 SysRAG\nContext for\nSAMP drafting 🟢"]
    end

    subgraph DD["Stage 2 · DD"]
        DD1["📄 DocAgent\nGap analysis\nCompetency reports 🟢"]
        DD2["🗄️ DBAgent\nAsset data import\nOCR legacy docs 🟢"]
        DD3["📊 SysDog\nGap scoring\nMaturity metrics 🟢"]
        DD4["🧠 SysLogicArh\nProcess mapping\nISO clause match 🟢"]
        DD5["🔐 SysPolic\nData ownership\nAccess rights 🟢"]
        DD6["🔧 SysMR\n— ⚫"]
        DD7["🔍 SysRAG\nLegacy doc\nsemantic search 🟢"]
    end

    subgraph EPC["Stage 3 · EPC"]
        EPC1["📄 DocAgent\nTech specs\nQA docs · ITPs 🟢"]
        EPC2["🗄️ DBAgent\nAsset register\nTagging & OCR 🟢"]
        EPC3["📊 SysDog\nMilestone tracking\nQuality metrics 🟢"]
        EPC4["🧠 SysLogicArh\nDesign ↔ Ops\nalignment 🟡"]
        EPC5["🔐 SysPolic\nDocument control\nChange approval 🟢"]
        EPC6["🔧 SysMR\nPunch list\nscripts 🟡"]
        EPC7["🔍 SysRAG\nSpec retrieval\nfor engineers 🟢"]
    end

    subgraph PO["Stage 4 · Pre-Ops"]
        PO1["📄 DocAgent\nSOPs · Permits\nSafety procs 🟢"]
        PO2["🗄️ DBAgent\nAs-built docs\nFinal registry 🟢"]
        PO3["📊 SysDog\nCommissioning\nqueues 🟢"]
        PO4["🧠 SysLogicArh\nOps ↔ Maint\ninterface 🟢"]
        PO5["🔐 SysPolic\nMoC activation\nPermit-to-work 🟢"]
        PO6["🔧 SysMR\nSystem config\nsetup scripts 🟢"]
        PO7["🔍 SysRAG\nProcedure lookup\nfor operators 🟢"]
    end

    subgraph OM["Stage 5 · O&M"]
        OM1["📄 DocAgent\nMaint plans\nIncident reports 🟢"]
        OM2["🗄️ DBAgent\nWork orders\nLog archiving 🟢"]
        OM3["📊 SysDog\nKPI dashboards\nFailure analysis\nModel fine-tuning 🟢"]
        OM4["🧠 SysLogicArh\nCross-dept sync\nContinuous AIMS 🟢"]
        OM5["🔐 SysPolic\nOngoing MoC\nAccess mgmt 🟢"]
        OM6["🔧 SysMR\nPreventive tasks\nRepair scripts\nScheduled patches 🟢"]
        OM7["🔍 SysRAG\nMaint knowledge\nbase 🟢"]
    end

    subgraph DECOM["Stage 6 · Decommission"]
        DECOM1["📄 DocAgent\nDisposal docs\nFinal reports 🟢"]
        DECOM2["🗄️ DBAgent\nArchive closure\nKnowledge transfer 🟢"]
        DECOM3["📊 SysDog\nFinal metrics\nLessons learned 🟢"]
        DECOM4["🧠 SysLogicArh\nHandover logic\nDept wind-down 🟡"]
        DECOM5["🔐 SysPolic\nFinal rights\ntransfer 🟢"]
        DECOM6["🔧 SysMR\nShutdown\nscripts 🟢"]
        DECOM7["🔍 SysRAG\nHistorical\nknowledge export 🟡"]
    end

    TEJ --> FEED --> DD --> EPC --> PO --> OM --> DECOM

    subgraph ORCH["⚙️ Orchestrator Layer — Active Across ALL Stages"]
        ORC["🧠 SysLogicArh acts as Interface Manager\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nRoutes tasks · Syncs agents · Auto-updates docs on any change\nValidates readiness gates between stages"]
    end

    ORCH -.->|"always active"| TEJ & FEED & DD & EPC & PO & OM & DECOM
```

---

## Project Escalation

```mermaid
graph TD
    Start((START)) --> L1["<b>Level 1: Project Leadership & Strategy</b><br/>Project Manager Agent / Strategic Alignment"]

    L2_1[Organizational Structure Agent]
    L2_2[Financial & Investment Agent]
    L2_3[Legal & Compliance Agent]

    L1 --> L2_1 & L2_2 & L2_3

    subgraph "Phase 1: Project Setup"
        L2_1
        L2_2
        L2_3
    end

    L3_1[Functional Doc Prep Agent: SAMP]
    L3_2[Functional Doc Prep Agent: Budget]
    L3_3[Functional Doc Prep Agent: Policy]

    L2_1 --> L3_1
    L2_2 --> L3_2
    L2_3 --> L3_3

    subgraph "Phase 2: Functional Document Preparation"
        L3_1
        L3_2
        L3_3
    end

    L4["<b>Interface Manager Agent</b><br/>Integrity Control & Synchronization"]

    L3_1 & L3_2 & L3_3 --> L4

    L5_1[Asset Integrity & Reliability Agent]
    L5_2[Operational Excellence Agent]
    L5_3[HSE & HR Safety Agent]

    L4 --> L5_1 --> L5_2 --> L5_3

    subgraph "Phase 3: Execution & Operations"
        L5_1
        L5_2
        L5_3
    end

    L6["<b>Dashboard & Analytics Agent</b><br/>Statistics, KPIs & Project Health"]

    L5_1 & L5_2 & L5_3 --> L6
    L6 -.->|Feedback Loop| L1

    style L1 fill:#f9f,stroke:#333,stroke-width:2px
    style L4 fill:#69f,stroke:#333,stroke-width:3px
    style L6 fill:#00ff00,stroke:#333,stroke-width:2px
```

---

## Document Generation Agent Structure

```mermaid
graph TD
    subgraph "Phase 1 — The Hook: Engineer Assistant"
        A[Individual Engineer] -->|Natural language request| B("AI Document Assistant\nAxi Bot")
        B -->|"Dual pipeline, Logic: R1-70B → Qwen-72B"| C[Structured Document Draft]
        C -->|"Cloud Quality Gate\nISO 45001 · ISO 21502 · IEC 82079"| D{"Score ≥ 80%?"}
        D -->|Yes| E["✅ Approved Document .docx"]
        D -->|No| F[Qwen revises with recommendations]
        F --> D
    end

    subgraph "Phase 2 — Multi-Agent Orchestration"
        E --> G{AIMS Orchestrator}
        G --> H["📊 Financial Department Orchestration Agent"]
        G --> I["⚠️ Risk & Safety Agent"]
        G --> J["📋 Technical Standards Agent"]
        G --> K["📁 Registry & OCR Agent"]
    end

    subgraph "Phase 3 — Enterprise Hub: Bot Factory"
        H & I & J & K --> L[("Single Source of Truth\naims_registry.db")]
        L --> M["🔍 Backend Reliability Agents\nArgus Monitor"]
        M --> N["🏢 On-Premise / Cloud\nCorporate Solution"]
    end

    style B fill:#c084fc,stroke:#7e22ce,stroke-width:2px,color:#fff
    style E fill:#4ade80,stroke:#166534,stroke-width:2px
    style L fill:#60a5fa,stroke:#1d4ed8,stroke-width:2px
    style N fill:#34d399,stroke:#065f46,stroke-width:3px
```

---

## 🟢 Live System Architecture
> What is built and running **today** with real engineers

```mermaid
flowchart TB
    subgraph Channels
        TG["Telegram Groups\nEngineers · PM · QA"]
    end

    subgraph "Agent Layer — Production ✅"
        Axi["📄 Axi Bot · DocAgent\nExternal reasoning\nGemini API + Anthropic\n✅ Production"]
        Omi["🗄️ Omi Bot · DBAgent\nRegistry · OCR pipeline\nLocal Qwen 7B\n✅ Production"]
        Argus["📊 Argus Bot · SysDog\nSystem monitor\nDevOps orchestrator\n✅ Production"]
    end

    subgraph "Doc Generation Pipeline — Production ✅"
        R1["deepseek-r1:70b\nDraft generation\nDGX Spark"]
        Qwen["qwen2.5:72b\nFormatting & revision\nDGX Spark"]
        Gemini["Gemini Flash/Pro\nISO compliance scoring\n0.0 – 1.0"]
    end

    subgraph "Data Layer — Production ✅"
        OR[("omi_registry.db\nOCR queue")]
        AR[("aims_registry.db\nMaster documents\n+ processes")]
        TRN[("Training data\ngold_pairs.jsonl\ndpo_pairs.jsonl")]
    end

    subgraph "Next Deployment 🔜"
        NL["🧠 SysLogicArh\nLogic & AIMS sync"]
        NP["🔐 SysPolic\nPolicy & rights gate"]
        NM["🔧 SysMR\nRepair & maintenance"]
        NR["🔍 SysRAG\nSemantic memory\n→ integrate into Omi"]
    end

    TG --> Axi & Omi
    Axi -->|Doc request| R1
    R1 -->|Draft| Qwen
    Qwen -->|Document| Gemini
    Gemini -->|Score + feedback| Qwen
    Qwen -->|"Final .docx"| TG
    Gemini -->|"score ≥ 0.8"| TRN
    Omi --> AR
    OR --> AR
    Argus -.->|Monitor| Axi & Omi & R1 & Qwen

    AR -.->|"feeds into"| NR
    Argus -.->|"scripts to"| NM
    NP -.->|"gates"| NM
    NL -.->|"orchestrates"| NP & NM & NR

    style Axi fill:#0d2137,stroke:#29b6f6,color:#e0f7fa
    style Omi fill:#0d2137,stroke:#4dd0e1,color:#e0f7fa
    style Argus fill:#0d2137,stroke:#81c784,color:#e0f7fa
    style NL fill:#1a0a2e,stroke:#9c6df4,color:#e9d5ff
    style NP fill:#1a0a2e,stroke:#f06292,color:#fce4ec
    style NM fill:#1a0a2e,stroke:#ffb74d,color:#fff3e0
    style NR fill:#1a0a2e,stroke:#4db6ac,color:#e0f2f1
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

| Standard | Scope |
|----------|-------|
| **ISO 55001:2024** | Asset management — Management systems — Requirements |
| **ISO 55002:2018** | Asset management — Guidelines for the application of ISO 55001 |
| **ISO 21502:2020** | Project management guidance |
| **ISO 21500:2021** | Project, programme and portfolio management concepts |
| **IEC/IEEE 82079-1:2019** | Preparation of information for use — technical documentation |
| **ISO 9001 §7.5** | Control of documented information |
| **ISO 45001** | Occupational health and safety management |
| **API RP 505** | Fire protection for refineries |

---

## ISO 55001 Clause Mapping to Plant Project Stages

| ISO 55001 Clause | Requirement | Plant Project Stage |
|------------------|-------------|---------------------|
| §4.1–4.3 | Context, stakeholders, scope | TEJ |
| §5.1–5.3 | Leadership, policy, roles | FEED |
| §6.1–6.2 | Risk framework, SAMP, objectives | FEED → DD |
| §7.1–7.5 | Resources, competence, documentation | DD → EPC |
| §8.1–8.4 | Operations, asset plans, MoC | EPC → PO → O&M |
| §9.1–9.3 | Monitoring, audit, management review | O&M |
| §10.1–10.3 | Improvement, corrective action | O&M → continuous |

---

## Document & OCR Pipeline

```mermaid
flowchart LR
    O["📁 Outbox / Uploads"] --> R["OCR Register\nomi_register.py"]
    R --> ODB[("omi_registry.db")]
    ODB --> S["Sync to knowledge DB\nsync_ocr_to_aims.py"]
    S --> ADB[("aims_registry.db\n✅ documents + processes")]
    ADB --> BOT["Omi Bot\n+ optional RAG"]
    ADB --> AXI["Axi Bot\nSilent registry check"]
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
    SysLogicArh — Logic & sync agent   :a5, 2026-07, 3M
    SysPolic — Policy & rights agent   :a6, 2026-08, 2M
    SysMR — Maintenance & repair agent :a7, 2026-09, 3M
    SysRAG — Semantic memory layer     :a8, 2026-10, 2M
    section Phase 4 · Enterprise
    HTTP/API gateway                   :a9, 2026-11, 2M
    On-premise enterprise deployment   :a10, 2026-12, 4M
    Corporate Bot Factory launch       :a11, 2027-03, 3M
```

---

## Repository Layout

```
AIMS-Agent-Orchestrator/
├── README.md                    ← this file
├── LICENSE                      (Apache-2.0)
├── docs/
│   ├── ARCHITECTURE.md          system design details
│   ├── DEMO_SCENARIO.md         step-by-step demo guide
│   ├── STANDARDS_MAPPING.md     ISO/IEC clause → agent capability
│   └── EMAILS_STARTUP_CREDITS.md
├── examples/
│   └── doc_agent_example.py     minimal usage example
└── docker-compose.yml           evaluation setup (optional)
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
