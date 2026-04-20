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

An **industrial multi-agent platform** for the launch of production projects, based on the **Asset Integrity Management System (AIMS)** approach (ISO 55001, ISO 55002), enables optimization of resources and timelines for pilot project deployment. The platform is designed for extension across all project lifecycle stages — from FEED through decommissioning — with further scalability to support full-cycle AIMS implementation.

---
## 🗺️ AIMS Process Framework — GFMAM Asset Management Landscape

The AxiOMSphere agent factory is structured around the **GFMAM Asset Management Landscape** — 8 subject areas forming the complete ISO 55001-aligned process framework. Each AxiOMSphere agent type maps directly to one or more of these subject areas.

![GFMAM Asset Management Landscape](docs/photo_2026-04-20_13-53-36.jpg)

> *Global Forum on Maintenance and Asset Management (GFMAM) — aligned with ISO 55001:2024*


## Plant Project Development Sequence

**Diagram 2 — ISO-Aligned Project Lifecycle (AIMS approach)**

```mermaid
flowchart TD
    START([▶ Industrial Project Initiated])

    START --> TEJ["Stage 0 — TEJ\nTechnical & Economic Justification\nISO 21502 §4.4 · ISO 55001 §6.1"]

    TEJ --> FEED["Stage 1 — FEED\nFront-End Engineering Design\nISO 21502 §7 · IEC 82079-1 §5"]

    FEED --> DD["Stage 2 — Detailed Design\nEngineering scope freeze · Basis of Design\nISO 21502 §8.3 · ISO 9001 §8.3"]

    DD --> EPC["Stage 3 — EPC\nEngineering · Procurement · Construction\nISO 21502 §8 · ISO 45001 §8.1"]

    EPC --> PO["Stage 4 — Pre-Operations\nCommissioning · Handover · Acceptance\nISO 21502 §9 · ISO 55001 §8.1"]

    PO --> OM["Stage 5 — O&M\nOperations & Maintenance\nISO 55001 §8.1 · ISO 55002 §8.1"]

    OM --> IMP["Stage 6 — Improvement\nAudit · Management Review · PDCA\nISO 55001 §10 · ISO 9001 §10.3"]

    IMP --> DEC["Stage 7 — Decommissioning\nSafe Disposal & Project Closure\nISO 55001 §8.1.3"]

    DEC --> DONE([✅ Industrial Project Closed])

    IMP -.->|PDCA loop| OM

    style START fill:#4ade80,stroke:#166534,color:#000
    style DONE  fill:#4ade80,stroke:#166534,color:#000
    style TEJ   fill:#60a5fa,stroke:#1d4ed8,color:#000
    style FEED  fill:#60a5fa,stroke:#1d4ed8,color:#000
    style DD    fill:#60a5fa,stroke:#1d4ed8,color:#000
    style EPC   fill:#60a5fa,stroke:#1d4ed8,color:#000
    style PO    fill:#60a5fa,stroke:#1d4ed8,color:#000
    style OM    fill:#60a5fa,stroke:#1d4ed8,color:#000
    style IMP   fill:#c084fc,stroke:#7e22ce,color:#fff
    style DEC   fill:#94a3b8,stroke:#475569,color:#000
```

---

## The Problem

At the industrial (plant/facility/EP oilfield) project justification stage, there is a critical need for empirical data, guiding documentation, and foundational decisions that will shape the project's development. These early choices can ultimately determine either the failure or the economic success of the enterprise.

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
    HEADER["🏭 AxiOMSphere Facility — Agent Type Registry\ Axi

bot\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nAxiOMSphere · Asset Integrity Management · Operations & Maintenance · Sphere"]

    HEADER --> T1 & T2 & T3 & T4 & T5 & T6 & T7

    T1["📄 DocAgent\n━━━━━━━━━━━━━━━━━\nDoci Bot\n─────────────────\nCorporate document generation\nfor AIMS launch & operations\nPipeline: R1-70B → Qwen-72B\n→ Cloud AI LLM ISO scoring ≥ 80%\n─────────────────\n⚡ Parallel per department\n✅ Production"]

    T2["🗄️ DBAgent\n━━━━━━━━━━━━━━━━━\nOmi Bot\n─────────────────\nDocument archive · OCR pipeline\nRAG semantic memory layer\nSingle Source of Truth\naims_registry.db\n─────────────────\n🔄 Always active\n✅ Production + Extend"]

    T3["📊 SysDog\n━━━━━━━━━━━━━━━━━\nArgus Bot\n─────────────────\nKPI collection & monitoring\nScheduler · Queue orchestration\nCyclic maintenance plans\nFailure analysis · Model tuning\nTraining loop supervision\n─────────────────\n🔄 Continuous\n✅ Production"]

    T4["🧠 SysLogicArh\n━━━━━━━━━━━━━━━━━\nLogi Bot\n─────────────────\nLogic & synchronization\nCross-dept AIMS alignment\nFunctional interface mapping\nSAMP adherence verification\nDept ↔ Dept coherence\n─────────────────\n⚡ Parallel per process\n🔜 Next deploy"]

    T5["🔐 SysPolic\n━━━━━━━━━━━━━━━━━\nPoli bot\n─────────────────\nAccess rights & permissions\nDocument ownership registry\nMoC control & registration\nSecurity policy enforcement\nModification gate keeper\n─────────────────\n🔒 Blocking gate\n🔜 Next deploy"]

    T6["🔧 SysMR\n━━━━━━━━━━━━━━━━━\nMainy Bot\n─────────────────\nReceives ready repair scripts\nfrom SysDog analysis\nExecutes code fixes & patches\nSystem file modifications\nScheduled maintenance tasks\nRequires SysPolic approval\n─────────────────\n⚡ Scheduled / on-demand\n🔜 Next deploy"]

    T7["🔍 SysRAG\n━━━━━━━━━━━━━━━━━\nKnomi bot\n─────────────────\nSemantic search layer\nContext provider for all agents\nVector index over aims_registry\nInter-agent knowledge requests\nEmbedding: nomic / BGE\n─────────────────\n🔄 Background / on-demand\n🔜 Integrate into DBAgent"]

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

    S0["📋 Stage 0 · TEJ\nTechnical-Economic Justification\nISO §4.1 Context · §4.2 Stakeholders · §4.3 Scope\n─────────────────────────────────\nFeasibility study & business case\nStakeholder identification & requirements\nDefine AMS scope & field of variation\nInvestment decision & project approval"]

    S1["🔭 Stage 1 · Pre-FEED\nConceptual Engineering\nISO §5.2 Policy · §6.2 Objectives\n─────────────────────────────────\nConcept selection & screening\nHigh-level cost estimate Class 5\nProject Scope Definition\nAIMS philosophy & objectives alignment\nInitial risk register"]

    S2["🎯 Stage 2 · FEED\nFront End Engineering Design\nISO §5 Leadership · §6 Planning\n─────────────────────────────────\nBasis of Design (BoD)\nProcess Flow Diagrams (PFD) · P&IDs\nHAZOP · Safety studies\nEquipment list · Datasheet package\nCost estimate Class 3\nProject Execution Plan (PEP)\nSAMP — Strategic Asset Mgmt Plan §6.2\nOrganizational structure · RACI §5.3\nFEED Package → EPC tender basis"]

    S3["🔍 Stage 3 · DD\nDetail Design\nISO §7 Support · §6.1 Risk\n─────────────────────────────────\nGap analysis vs ISO 55001 requirements\nAsset inventory & criticality assessment\nCompetency assessment & training plan §7.2\nData standards & ownership §7.5\nContractor qualification & selection\nEPC contract award"]

    S4["⚙️ Stage 4 · EPC\nEngineering · Procurement · Construction\nISO §8.1 Operational Planning · §8.3 Outsourcing\n─────────────────────────────────\nDetailed engineering · Vendor packages\nProcurement control & supplier qualification\nConstruction · QA/QC · Inspection\nPunch list A & B management\nAsset register build · Tag numbers\nMC Dossier preparation · As-built drawings"]

    S5["🚀 Stage 5 · Commissioning & Startup\nMC → Commissioning → RFSU → PAC → FAC\nISO §8.2 Asset Mgmt Plans · §8.4 Change Mgmt\n─────────────────────────────────\nMC: Mechanical Completion · Punch list A cleared\nCommissioning: Pre-startup audit · System checks\nRFSU: Ready For Start-Up · Performance tests\nPAC: Provisional Acceptance · Final documentation\nFAC: Final Acceptance · Defects correction closure\nSOP development · MoC activation · Permit-to-work\nHandover dossiers Books A–L"]

    S6["🏭 Stage 6 · Operation & Maintenance\nISO §8 Operation · §9 Evaluation · §10 Improvement\n─────────────────────────────────\nOperational control & monitoring §8.1\nPreventive & predictive maintenance strategies\nRBI · NDT · Risk-based inspection planning\nKPI tracking & performance review §9.1\nIncident investigation · RCA · Lessons learned §10.1\nInternal & external audits · ISO 55001 certification §9.2\nContinuous improvement · SAMP update · PDCA loop"]

    DONE(["✅ AIMS FULLY OPERATIONAL\nISO 55001 Certified Enterprise"])

    START --> S0 --> S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> DONE

    S6 -.->|"PDCA Loop · Plan → Do → Check → Act"| S2

    style START fill:#1a1a2e,stroke:#4fc3f7,color:#fff
    style S0 fill:#0a1628,stroke:#4fc3f7,color:#b3e5fc
    style S1 fill:#0d2b0d,stroke:#69f0ae,color:#ccff90
    style S2 fill:#0a2010,stroke:#66bb6a,color:#c8e6c9
    style S3 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style S4 fill:#1c0e00,stroke:#ffa726,color:#ffe0b2
    style S5 fill:#1c0000,stroke:#ef5350,color:#ffcdd2
    style S6 fill:#0d1b33,stroke:#42a5f5,color:#bbdefb
    style DONE fill:#003300,stroke:#66bb6a,color:#e8f5e9
```

### Diagram 3A — Agent Build, Test & Tuning Sequence (Flowchart):

```mermaid
flowchart TD
    START(["🏭 AxiOMSphere Factory\nAgent Build · Test · Tune Program"])

    subgraph PROD["✅ PRODUCTION — Already Built & Testing"]
        P1["📄 Axi Bot · DocAgent\n─────────────────\nBuild: DeepSeek-R1-70B → Qwen2.5-72B → Cloud API LLM pipeline\nTest: ISO compliance score ≥ 80%\nTune: qwen2.5-14B · 6 cycles done ✅\nNext: qwen2.5-72B tuning 🔄\nTarget: score ≥ 0.85 · latency < 10 min"]
        P2["🗄️ Omi Bot · DBAgent\n─────────────────\nBuild: OCR pipeline + aims_registry.db\nTest: Document registration accuracy\nTest: RAG semantic search precision\nTune: Embedding model nomic/BGE\nTarget: retrieval precision ≥ 90%"]
        P3["📊 Argus Bot · SysDog\n─────────────────\nBuild: DevOps monitor + queue scheduler\nTest: KPI collection · Alert triggers\nTest: Training loop gold/DPO pairs\nTune: Failure detection thresholds\nTarget: uptime ≥ 99.5% · MTTR < 5 min"]
        P4["📄 DocAgent · standalone\n─────────────────\nBuild: Independent doc generation module\nTest: Multi-format output · DOCX quality\nTest: ISO clause mapping accuracy\nTune: Prompt templates per doc type\nTarget: ISO score ≥ 0.80 on all doc types"]
    end

    START --> PROD

    PROD --> GATE1{{"🔒 Gate 1\nProduction agents stable?\nScore targets met?\nArgus monitoring active?"}}

    GATE1 -->|"❌ Fail"| FIX1["🔧 Failure Analysis Loop\n─────────────────\nSysDog collects failure logs\nRCA — Root Cause Analysis\nGenerate fix scripts\nRetune model · Retest\nUpdate gold_pairs.jsonl"]
    FIX1 --> GATE1

    GATE1 -->|"✅ Pass"| NEXT1

    subgraph NEXT1["🔜 NEXT DEPLOY — Phase 3"]
        N1["🧠 SysLogicArh\n─────────────────\nBuild: AIMS sync engine\nInterface mapping logic\nTest: Cross-dept doc coherence\nTest: SAMP alignment verification\nTest: Dept ↔ Dept conflict detection\nTfine-tuning: Qwen2.5-72B with crosscheck DeepSeel-R1:70B on AIMS corpus\nTarget: 0 logic conflicts in 100 docs"]
        N2["🔐 SysPolic\n─────────────────\nBuild: Rights & permissions engine\nMoC registration module\nTest: Access control enforcement\nTest: Document ownership tracking\nTest: Change approval workflow\nTfine-tuning: Qwen2.5-72B with crosscheck DeepSeel-R1:70B\Policy rule base fine-tuning\nTarget: 100% MoC compliance · 0 breaches"]
    end

    NEXT1 --> GATE2{{"🔒 Gate 2\nSysLogicArh coherence ≥ 95%?\nSysPolic 0 access breaches?\nMoC workflow validated?"}}

    GATE2 -->|"❌ Fail"| FIX2["🔧 Failure Analysis Loop\n─────────────────\nLog conflict patterns\nRCA on policy violations\nRetune logic rules\nRetest full workflow"]
    FIX2 --> GATE2

    GATE2 -->|"✅ Pass"| NEXT2

    subgraph NEXT2["🔜 NEXT DEPLOY — Phase 4"]
        N3["🔧 SysMR\n─────────────────\nBuild: Script execution engine\nScheduled maintenance runner\nTest: Script safety validation\nTest: Rollback on failure\nTest: SysPolic approval gate\nTest: Scheduled task accuracy\nTune: R1-70B on repair corpus\nTarget: 0 unauthorized changes\n100% rollback success on fail"]
        N4["🔍 SysRAG\n─────────────────\nBuild: Vector index over aims_registry\nSemantic search API for agents\nTest: Retrieval relevance score\nTest: Inter-agent query response\nTest: Context window optimization\nTune: nomic-embed · BGE models\nTarget: relevance ≥ 0.90\nlatency < 2 sec per query"]
    end

    GATE2 --> NEXT2

    NEXT2 --> GATE3{{"🔒 Gate 3\nSysMR 0 unauthorized changes?\nSysRAG relevance ≥ 0.90?\nAll 7 agents integrated?\nOrchestrator routing stable?"}}

    GATE3 -->|"❌ Fail"| FIX3["🔧 Failure Analysis Loop\n─────────────────\nFull system integration test\nEnd-to-end doc generation test\nRCA on integration failures\nTune all models · Retest"]
    FIX3 --> GATE3

    GATE3 -->|"✅ Pass"| DONE

    subgraph TUNE["🔄 Continuous Tuning Loop — All Stages"]
        T1["qwen2.5-14B\n6 cycles done ✅\nBaseline established"]
        T2["qwen2.5-72B\nIn progress 🔄\nTarget: score ≥ 0.85"]
        T3["deepseek-r1:70b\nNext after 72B\nTarget: draft quality +15%"]
        T4["Cloud API LLM/Pro\nISO scoring gate\nTarget: 0.0–1.0 calibrated"]
        T1 --> T2 --> T3
        T3 -.->|"scoring"| T4
    end

    TUNE -.->|"feeds improvement"| FIX1 & FIX2 & FIX3

    DONE(["✅ AxiOMSphere FULLY OPERATIONAL\n7 Agents · ISO 55001 Compliant\nCorporate Bot Factory Ready"])

    style START fill:#0d1117,stroke:#58a6ff,color:#e6edf3
    style DONE fill:#003300,stroke:#66bb6a,color:#e8f5e9
    style GATE1 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style GATE2 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style GATE3 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style FIX1 fill:#1c0000,stroke:#ef5350,color:#ffcdd2
    style FIX2 fill:#1c0000,stroke:#ef5350,color:#ffcdd2
    style FIX3 fill:#1c0000,stroke:#ef5350,color:#ffcdd2
    style PROD fill:#003300,stroke:#66bb6a,color:#c8e6c9
    style NEXT1 fill:#0a1628,stroke:#4fc3f7,color:#b3e5fc
    style NEXT2 fill:#1a0a2e,stroke:#9c6df4,color:#e9d5ff
    style TUNE fill:#1b0033,stroke:#ce93d8,color:#f3e5f5
```


## Diagram 3B — AxiOMSphere Deployment Roadmap (Gantt): AxiOMSphere
### AxiOMSphere / AIMS — Master Deployment Roadmap 

```mermaid
gantt
    title AxiOMSphere - Master Agent Deployment Roadmap
    dateFormat  YYYY-MM-DD

    section Phase 1 - Foundation
    DocAgent and DBAgent registry OCR baseline                :done, p1a, 2025-10-01, 2026-01-31
    Axi and Omi production hardening                          :done, p1b, 2026-02-01, 2026-03-31
    SysDog monitoring KPI and alerts                          :done, p1c, 2026-04-01, 2026-04-30
    Gate A Foundation ready                                   :done, gA, 2026-05-01, 2026-05-02

    section Phase 2 - Intelligence
    Dual pipeline R1 to Qwen to Gemini scoring                :done, p2a, 2026-03-01, 2026-04-30
    Fine tuning loop gold set and DPO                         :active, p2b, 2026-04-01, 2026-06-30
    Model quality calibration and evaluator alignment         :active, p2c, 2026-07-01, 2026-08-31
    Gate B Model quality and safety                           :active, gB, 2026-09-01, 2026-09-02

    section Phase 3 - Agent Mesh
    SysLogicArch cross agent logic and sync build             :p3a, 2026-07-01, 2026-08-31
    SysPolicy rights ownership approval build                 :p3b, 2026-08-01, 2026-09-30
    SysMR maintenance and repair guardrails build             :p3c, 2026-09-01, 2026-10-31
    SysRAG semantic memory and retrieval build                :p3d, 2026-10-01, 2026-11-30
    Mesh integration test seven agent orchestration           :p3e, 2026-12-01, 2027-01-31
    Gate C Multi agent integration validated                  :gC, 2027-02-01, 2027-02-02

    section Phase 4 - Enterprise Delivery
    HTTP API gateway and auth controls                        :p4a, 2026-11-01, 2026-12-31
    On prem enterprise deployment                             :p4b, 2027-02-01, 2027-05-31
    ISO 55001 pre audit and corrective actions                :p4c, 2027-06-01, 2027-06-30
    ISO 55001 certification audit                             :p4d, 2027-07-01, 2027-07-31
    Corporate Bot Factory launch                              :gD, 2027-08-01, 2027-08-02
```

### Gate KPI Criteria (add under the chart in README)

- **Gate A — Foundation ready**
  - OCR/register->sync success rate >= 98% for 30 days.
  - P95 document retrieval latency <= 5s for top workflows.
  - SysDog alerting active with owner response runbook.

- **Gate B — Model quality and safety**
  - Retrieval relevance >= 0.85 on validation set.
  - Structured action format compliance >= 95%.
  - Hallucination rate in critical document answers <= 3%.

- **Gate C — Multi-agent integration validated**
  - 7-agent orchestration pass rate >= 95% on scenario suite.
  - Zero critical access-control violations (SysPolicy).
  - Cross-agent handoff completion <= 15s P95.

- **Gate D — Enterprise launch readiness**
  - UAT sign-off by operations + QA + document control leads.
  - MTTR for platform incidents <= 30 minutes in pilot.
  - Audit nonconformities closed or formally accepted.

### Gate Flow (for pitch deck)

```mermaid
flowchart LR
    A["Gate A\nFoundation ready"] --> B["Gate B\nModel quality and safety"]
    B --> C["Gate C\nMulti-agent integration validated"]
    C --> D["Gate D\nEnterprise launch readiness"]

    A --- A1["OCR/sync >= 98%\nRetrieval P95 <= 5s"]
    B --- B1["Relevance >= 0.85\nFormat compliance >= 95%"]
    C --- C1["7-agent pass >= 95%\n0 critical policy breaches"]
    D --- D1["UAT signed\nMTTR <= 30m\nAudit closed"]
```


## Industrial Project Escalation

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
![GFMAM Asset Management Landscape](docs/axiompshere_roadmap_2028_final.svg)


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
