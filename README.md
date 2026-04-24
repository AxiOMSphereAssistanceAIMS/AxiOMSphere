# AxiOMSphere
> **Multi-agent AI platform that automates industrial engineering workflows — from document generation to ISO compliance — using coordinated LLM agents running on private infrastructure.**

[🌐 Website](https://axiomsphereaassistanceaims.github.io/AIMS-Agent-Orchestrator/) · [📺 Demo](#demo) · [📬 Contact](#contact) · [📋 Apply for Credits](#grant-applications)

---

## What We Do

AxiOMSphere replaces manual project startup engineering work with coordinated AI agents. Each agent handles one function — document generation, quality control, registry management, infrastructure monitoring — and they operate as a continuous pipeline.

**The result is 1,5 year for 1 month:**
-  A document describing a business process, typically written in 2-3 days each by several specialists from different disciplines (recruited for a specific project), can be created in less than 10 minutes within an integrated functional system within a single functional area, in accordance with the AIMS project philosophy (a total of 1.5 years of work in 1 month). Even by non-experts or department heads, it allows for task assignments via chat, voice, or text, from any location. The database is based on several projects, providing valuable experience.
- ISO compliance verified automatically, not by hand
- Every generation run feeds back into model training — the system improves with every use

We're currently working in production with live engineers and actively scaling usage. We expect significant demand for the API in the next 1-3 months as the team expands and new types of documentation, tests, and cross-validations are added.

---

## Business Impact

| Before AxiOMSphere | With AxiOMSphere |
|-------------------|-----------------|
| 2–3 days to write a Oeration & Maintenance procedure | 5–10 minutes, reviewed and delivered to Telegram |
| 20 engineers / 2 DCC specialists / 5 department heads / 2 HR specialists to write 1000 procedures for 1.5 years | 5 engineers (hybrid work), 5-10 minutes, problem formulation 10 minutes, 1000 documents will be checked and sent to Telegram and saved in the database with full compliance with the company format and banding within 14 days |
| Any change in functionality in the vertical distribution chain will require a process of revising the upstream documents of 1000 procedures for 1.5 years | An integrated system capable of independently reviewing and comparing functionality and interface interactions is capable of restoring discrepancies in documents in a matter of hours, even without the process of revising them |
| ISO compliance checked manually, often skipped | Automated scoring 0.0–1.0, rewrite loop until ≥80% |
| Knowledge locked in PDFs on shared drives | Searchable, versioned, semantically indexed master documents registry |
| Model training requires a separate team | Every production run generates gold + DPO training pairs automatically |
| Infra issues noticed when users complain | Argus monitors 24/7, auto-restarts, alerts with one-click fix (every one has unic function) |

---

## Why We Need API Credits

AxiOMSphere is a **high-frequency, multi-agent system** where every user task decomposes into coordinated agent stages:

```
User request → Planning → Draft (R1-70B) → Rewrite (Qwen-72B) → Score (Gemini) → Revise → Register → Notify
```

Unlike a single-prompt application, **one document workflow requires 20–100+ LLM calls**:
- Complince agent: standart's identification by context (allocation for ISO55001/55002)
- Reasoning agent: structural outline + ISO clause mapping to standard ISO 9000:2015:
- Rewrite agent: professional formatting pass ISO 19005-1:2005
- Quality gate: compliance scoring + gap feedback
- Revision loop: targeted rewrites until score ≥ 80%
- Registry agent: classification, embedding, storage

**Expected usage as we scale:**
- Workflows run continuously (CI/CD-style, nightly pipeline)
- Multiple agents operate in parallel per task
- Every scaling step compounds token consumption

**What credits enable:**
1. Validate multi-agent orchestration at production scale
2. Optimize prompt strategies across model configurations
3. Benchmark admin 14B / coding 32/ logical 70B / fine formating 72B quality vs. the highest documents tuned cloud model tradeoffs
4. Create production-ready automated pipelines for broader enterprise document processing and localization in professional collection databases. 

Without sufficient API capacity it is not possible to realistically simulate or validate real-world agent workloads at the volume our architecture is designed for.

> We are not building a chatbot. We are building a system designed for sustained, large-scale LLM usage where API consumption is a core component of the product.

---

## Demo

**Scenario: Automated Safety Document Generation**

```
Input:  "developing a preservation procedure for an Aluminum plant, as requested. The procedure was being structured as a
        Word document (.docx) with initial sections covering Purpose, Scope, and Definitions, and was designed to incorporate
        the specified subcomponents: Power Plant, Power Distribution (HV/LV), Paste Plant, Anode Baking Plant, Bath Crushing
        Plants, Pot Lines, Fume Treatment Plant, Cast House, Port Facilities, and Utilities.
         Reference ISO 55001. The AIMS process database synchronization."

Stage 1 — Planning agent      (~30 sec)
  → Identifies: JSA template, applicable OSHA 29 CFR 1910.147 local corporate manuals and procedures based on equipment types
  → Outlines: scope, equipment types identification sections, control hierarchy

Stage 2 — Draft agent: deepseek-r1:70b   (~5 min)
  → Generates structured draft with ISO 10013 / ISO/IEC Directives -aware section headers
  → Produces hazard table with risk matrix, elimination → substitution → PPE controls

Stage 3 — Rewrite agent: qwen2.5:72b     (~3 min)
  → Professional formatting, paragraph cohesion, terminology standardization ISO 2145:1978

Stage 4 — Compliance gate: Gemini Flash  (~15 sec)
  → Score: 0.84 / 1.0
  → Feedback: "Add specific corrections and specification per ....."

Stage 5 — Revision: qwen2.5:72b          (~2 min)
  → Target correction applied, assessment re-checked (knowledge base and lessons learned in background)

Output: JSA_confined_space_entry.docx → delivered to Telegram
        ISO compliance: 84%   |   Total time: ~11 min
        Training pair saved → gold_pairs.jsonl (score ≥ 0.8)
```

[📺 Video demo coming soon] · [🖼 Architecture](docs/ARCHITECTURE.md)

---

## Use Cases in Production Today

| Task | Document type | Standard | Time |
|------|--------------|----------|------|
| AIMS philosophies | Asset Management systems - Guidelines | ISO 55001/55002 | ~10 min |
| Procedures Equipment types, unites scope, standart requirement | Equipment isolation procedure + requirement matrix | OSHA 29 CFR 1910.147 local corporate manuals and procedures | ~12 min |
| Pump replacement — change control | Management of Change (MOC) | ISO 45001 §8.1.3 | ~8 min |
| New asset onboarding | Asset Management Plan | ISO 55001 §8.2 | ~15 min |
| Project kick-off package | Charter + WBS | ISO 21502 | ~20 min |
| Technical operating manual | User documentation | IEC 82079-1 | ~18 min |

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
# → Feedback: "Document covers all required JSA sections with complete hazard controls matrix."
```

---

## 🟢 Live System — What Runs Today

```mermaid
flowchart TB
    subgraph Channels
        TG["Telegram Groups\nEngineers · PM · QA"]
    end

    subgraph "Agent Layer — Production ✅"
        Axi["📄 Axi Bot\nDocument generation\nGemini API + Anthropic\n✅ Production"]
        Omi["🗄️ Omi Bot\nDocument registry\nOCR pipeline · RAG\n✅ Production"]
        Argus["📊 Argus Bot\nInfra monitor · Scheduler\nTraining loop supervision\n✅ Production"]
    end

    subgraph "Doc Generation Pipeline — Production ✅"
        R1["deepseek-r1:70b\nReasoning + draft\nDGX Spark"]
        Qwen["qwen2.5:72b\nRewrite + revision\nDGX Spark"]
        Gemini["Gemini Flash/Pro\nISO compliance score\n0.0 – 1.0"]
    end

    subgraph "Data Layer — Production ✅"
        AR[("aims_registry.db\nMaster document registry")]
        TRN[("gold_pairs.jsonl\ndpo_pairs.jsonl\nAuto-saved every run")]
    end

    subgraph "Next Deployment 🔜"
        NL["🧠 SysLogicArh\nCross-dept AIMS sync"]
        NP["🔐 SysPolic\nAccess rights · MoC gate"]
        NM["🔧 SysMR\nMaintenance automation"]
        NR["🔍 SysRAG\nSemantic memory layer"]
    end

    TG --> Axi & Omi
    Axi -->|"doc request"| R1 --> Qwen --> Gemini
    Gemini -->|"score + feedback"| Qwen
    Qwen -->|"Final .docx"| TG
    Gemini -->|"score ≥ 0.8 → saved"| TRN
    Omi --> AR
    Argus -.->|"monitor + schedule"| Axi & Omi & R1 & Qwen
    AR -.-> NR
    Argus -.-> NM
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

## How It Works

### Doc Generation Pipeline

| Stage | Model | Role | Time |
|-------|-------|------|------|
| **Draft** | deepseek-r1:70b | ISO-aware reasoning, structural outline | ~5 min |
| **Rewrite** | qwen2.5:72b | Professional formatting, terminology | ~3 min |
| **Score** | Gemini Flash/Pro | Compliance 0.0–1.0, gap feedback | ~15 sec |
| **Revise** | qwen2.5:72b | Targeted fix per Gemini feedback | ~2 min |

Quality gate: <60% → reject + retry · ≥60% → accepted · target **98% compliance**

### NLP Intent Routing

All 3 bots use a local fine-tuned model (`chat_intent_router.py`) to classify free-text messages into slash commands **before** any cloud LLM call — keeping latency low and cloud costs minimal:

```
"check if DGX is up"  →  /dgx status
"show stuck tasks"    →  /tasks --stuck
"generate MOC doc"    →  /doc --type=moc
```

### Continuous Training Loop

Every production run auto-saves training pairs — no opt-in flag needed:
- `gold_pairs.jsonl` — document + task pairs scoring ≥ 0.8
- `dpo_pairs.jsonl` — preference pairs for RLHF

These feed the nightly fine-tuning pipeline (14B → 70B → 72B), so the system improves as it operates.

---

## Agent Architecture — 7 Types

```mermaid
flowchart TD
    HEADER["🏭 AxiOMSphere — Agent Type Registry"]

    HEADER --> T1 & T2 & T3 & T4 & T5 & T6 & T7

    T1["📄 DocAgent\nDoci Bot\n─────────────────\nCorporate document generation\nR1-70B → Qwen-72B\n→ Cloud AI ISO scoring ≥ 80%\n⚡ Parallel per department\n✅ Production"]

    T2["🗄️ DBAgent\nOmi Bot\n─────────────────\nDocument archive · OCR pipeline\nRAG semantic memory\nSingle Source of Truth\naims_registry.db\n🔄 Always active\n✅ Production"]

    T3["📊 SysDog\nArgus Bot\n─────────────────\nKPI collection & monitoring\nScheduler · Queue orchestration\nFailure analysis · Model tuning\nTraining loop supervision\n🔄 Continuous\n✅ Production"]

    T4["🧠 SysLogicArh\nLogi Bot\n─────────────────\nLogic & synchronization\nCross-dept AIMS alignment\nFunctional interface mapping\nSAMP adherence verification\n⚡ Parallel per process\n🔜 Next deploy"]

    T5["🔐 SysPolic\nPoli Bot\n─────────────────\nAccess rights & permissions\nDocument ownership registry\nMoC control & registration\nSecurity policy enforcement\n🔒 Blocking gate\n🔜 Next deploy"]

    T6["🔧 SysMR\nMainy Bot\n─────────────────\nReceives repair scripts from SysDog\nExecutes fixes & patches\nScheduled maintenance tasks\nRequires SysPolic approval\n⚡ Scheduled / on-demand\n🔜 Next deploy"]

    T7["🔍 SysRAG\nKnomi Bot\n─────────────────\nSemantic search for all agents\nVector index over aims_registry\nEmbedding: nomic / BGE\n🔄 Background / on-demand\n🔜 Integrate into DBAgent"]

    style HEADER fill:#0d1117,stroke:#58a6ff,color:#e6edf3
```

---

## Project Nomenclature

**AxiOMSphere** is a strategic integration of four pillars:

| Part | Meaning |
|------|---------|
| **Axiom** | Foundational precision of international standards |
| **AIMS** | Asset Integrity Management System — central intelligence |
| **O&M** | Operations & Maintenance — highest-value lifecycle phase |
| **Sphere** | Unified 360° ecosystem — Single Source of Truth |

---

## AIMS Process Framework

The agent factory is structured around the **GFMAM Asset Management Landscape** — 8 subject areas forming the complete ISO 55001-aligned process framework.

![GFMAM Asset Management Landscape](docs/photo_2026-04-20_13-53-36.jpg)

> *Global Forum on Maintenance and Asset Management (GFMAM) — aligned with ISO 55001:2024*

---

## ISO-Aligned Project Lifecycle

AxiOMSphere covers all 7 stages of an industrial plant project:

```mermaid
flowchart TD
    START(["🏗️ PLANT PROJECT START"])

    S0["📋 Stage 0 · TEJ\nTechnical-Economic Justification\nISO §4.1 Context · §4.3 Scope\nFeasibility · Stakeholder requirements · Investment decision"]
    S1["🔭 Stage 1 · Pre-FEED\nConceptual Engineering\nISO §5.2 Policy · §6.2 Objectives\nConcept selection · Cost Class 5 · AIMS philosophy alignment"]
    S2["🎯 Stage 2 · FEED\nFront End Engineering Design\nISO §5 Leadership · §6 Planning\nBoD · PFD · HAZOP · SAMP · RACI · EPC tender basis"]
    S3["🔍 Stage 3 · Detail Design\nISO §7 Support · §6.1 Risk\nGap analysis · Asset inventory · Competency assessment · EPC award"]
    S4["⚙️ Stage 4 · EPC\nISO §8.1 Operational Planning\nDetailed engineering · Procurement · Construction · Asset register build"]
    S5["🚀 Stage 5 · Commissioning & Startup\nISO §8.2 Asset Mgmt Plans · §8.4 Change Mgmt\nMC → RFSU → PAC → FAC · SOP · MoC · Handover dossiers"]
    S6["🏭 Stage 6 · O&M\nISO §8 Operation · §9 Evaluation · §10 Improvement\nRBI · KPI tracking · Audits · ISO 55001 certification · PDCA"]

    DONE(["✅ AIMS FULLY OPERATIONAL"])

    START --> S0 --> S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> DONE
    S6 -.->|"PDCA Loop"| S2

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

---

## Deployment Roadmap

### Agent Build, Test & Tuning Sequence

```mermaid
flowchart TD
    START(["🏭 AxiOMSphere Factory\nAgent Build · Test · Tune"])

    subgraph PROD["✅ PRODUCTION — Built & Running"]
        P1["📄 Axi Bot · DocAgent\nR1-70B → Qwen2.5-72B → Cloud gate\nqwen2.5-14B: 7 fine-tune cycles ✅\nqwen2.5-72B: tuning in progress 🔄\nTarget: ISO score ≥ 0.85 · < 10 min"]
        P2["🗄️ Omi Bot · DBAgent\nOCR pipeline + aims_registry.db\nRAG semantic search\nTarget: retrieval precision ≥ 90%"]
        P3["📊 Argus Bot · SysDog\nDevOps monitor + queue scheduler\nTraining loop gold/DPO pairs\nTarget: uptime ≥ 99.5% · MTTR < 5 min"]
    end

    START --> PROD

    PROD --> GATE1{{"🔒 Gate 1\nScore targets met?\nArgus monitoring stable?"}}
    GATE1 -->|"❌ Fail"| FIX1["🔧 RCA Loop\nSysDog collects failure logs\nRetune model · Update gold_pairs"]
    FIX1 --> GATE1
    GATE1 -->|"✅ Pass"| NEXT1

    subgraph NEXT1["🔜 NEXT DEPLOY — Phase 3"]
        N1["🧠 SysLogicArh\nAIMS sync engine\nCross-dept coherence\nTarget: 0 logic conflicts in 100 docs"]
        N2["🔐 SysPolic\nRights & permissions engine\nMoC registration module\nTarget: 100% MoC compliance · 0 breaches"]
    end

    NEXT1 --> GATE2{{"🔒 Gate 2\nLogicArh coherence ≥ 95%?\nSysPolic 0 access breaches?"}}
    GATE2 -->|"❌ Fail"| FIX2["🔧 RCA Loop"]
    FIX2 --> GATE2
    GATE2 -->|"✅ Pass"| NEXT2

    subgraph NEXT2["🔜 NEXT DEPLOY — Phase 4"]
        N3["🔧 SysMR\nScript execution engine\nRollback on failure\nTarget: 0 unauthorized changes"]
        N4["🔍 SysRAG\nVector index over aims_registry\nInter-agent semantic search\nTarget: relevance ≥ 0.90 · < 2 sec"]
    end

    NEXT2 --> GATE3{{"🔒 Gate 3\nAll 7 agents integrated?\nOrchestrator routing stable?"}}
    GATE3 -->|"✅ Pass"| DONE

    subgraph TUNE["🔄 Continuous Tuning"]
        T1["qwen2.5-14B\n7 cycles ✅ baseline"] --> T2["qwen2.5-72B\nin progress 🔄"]
        T2 --> T3["deepseek-r1:70b\nnext after 72B"]
        T3 -.->|"scoring"| T4["Cloud Gate\n0.0–1.0 calibration"]
    end
    TUNE -.-> FIX1 & FIX2

    DONE(["✅ AxiOMSphere FULLY OPERATIONAL\n7 Agents · ISO 55001 Compliant"])

    style PROD fill:#003300,stroke:#66bb6a,color:#c8e6c9
    style NEXT1 fill:#0a1628,stroke:#4fc3f7,color:#b3e5fc
    style NEXT2 fill:#1a0a2e,stroke:#9c6df4,color:#e9d5ff
    style GATE1 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style GATE2 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style GATE3 fill:#1c1a00,stroke:#ffca28,color:#fff9c4
    style DONE fill:#003300,stroke:#66bb6a,color:#e8f5e9
    style TUNE fill:#1b0033,stroke:#ce93d8,color:#f3e5f5
```

### Master Timeline

```mermaid
gantt
    title AxiOMSphere — Master Deployment Roadmap
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

### Gate KPI Criteria

- **Gate A — Foundation ready:** OCR/sync ≥ 98% for 30 days · P95 retrieval ≤ 5s · SysDog alerting active
- **Gate B — Model quality:** Retrieval relevance ≥ 0.85 · Format compliance ≥ 95% · Hallucination ≤ 3% on critical docs
- **Gate C — Multi-agent integration:** 7-agent pass rate ≥ 95% · Zero SysPolicy violations · Cross-agent handoff P95 ≤ 15s
- **Gate D — Enterprise launch:** UAT signed · MTTR ≤ 30 min in pilot · Audit nonconformities closed

```mermaid
flowchart LR
    A["Gate A\nFoundation ready"] --> B["Gate B\nModel quality"]
    B --> C["Gate C\nAgent mesh"] --> D["Gate D\nEnterprise launch"]
    A --- A1["OCR ≥ 98%\nP95 ≤ 5s"]
    B --- B1["Relevance ≥ 0.85\nCompliance ≥ 95%"]
    C --- C1["7-agent ≥ 95%\n0 policy breaches"]
    D --- D1["UAT signed\nMTTR ≤ 30m"]
```

---

## Industrial Project Escalation

```mermaid
graph TD
    Start((START)) --> L1["Level 1: Project Leadership & Strategy\nProject Manager Agent / Strategic Alignment"]

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

    L4["Interface Manager Agent\nIntegrity Control & Synchronization"]
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

    L6["Dashboard & Analytics Agent\nStatistics, KPIs & Project Health"]
    L5_1 & L5_2 & L5_3 --> L6
    L6 -.->|Feedback Loop| L1

    classDef phase1 fill:#69b7ff,stroke:#333,stroke-width:2px,color:#000;
    class L2_1,L2_2,L2_3,L3_1,L3_2,L3_3 phase1;
    style L1 fill:#f9f,stroke:#333,stroke-width:2px
    style L4 fill:#69f,stroke:#333,stroke-width:3px
    style L6 fill:#00ff00,stroke:#333,stroke-width:2px
```

---

## Document Generation — Agent Structure

```mermaid
graph TD
    subgraph "Phase 1 — Engineer Assistant"
        A[Individual Engineer] -->|Natural language request| B("AI Document Assistant\nAxi Bot")
        B -->|"R1-70B → Qwen-72B dual pipeline"| C[Structured Document Draft]
        C -->|"Cloud Quality Gate\nISO 45001 · ISO 21502 · IEC 82079"| D{"Score ≥ 80%?"}
        D -->|Yes| E["✅ Approved Document .docx"]
        D -->|No| F[Qwen revises with recommendations]
        F --> D
    end
    E --> L["Master Document Registration\nin aims_registry.db"]

    style B fill:#c084fc,stroke:#7e22ce,stroke-width:2px,color:#fff
    style E fill:#4ade80,stroke:#166534,stroke-width:2px
    style L fill:#60a5fa,stroke:#1d4ed8,stroke-width:2px
```

---

## Document & OCR Pipeline

```mermaid
flowchart LR
    O["📁 Outbox / Uploads"] --> R["OCR Register\nomi_register.py"]
    R --> ODB[("omi_registry.db")]
    ODB --> S["Sync\nsync_ocr_to_aims.py"]
    S --> ADB[("aims_registry.db\n✅ documents + processes")]
    ADB --> BOT["Omi Bot\n+ RAG"]
    ADB --> AXI["Axi Bot\nSilent registry check"]
```

---

## Data Pipeline (Full)

```mermaid
flowchart TD
    A["👤 User sends file via Telegram"] --> B["inbox/income/"]
    B --> C["OCR Watcher (GPU)"]
    C --> D["outbox/ (text extracted)"]
    D --> E{"Quality Gate\nsimilarity ≥ 90%?"}
    E -->|"✅ pass"| F["aims_registry.db\n+ Qdrant embedding"]
    E -->|"❌ fail"| G["inbox/Skipped/"]
    F --> H["RAG Search"]
    H --> I["DocAgent — Qwen 72B DGX"]
    I --> J["generated/*.docx → Telegram"]
    style F fill:#1a4731
    style G fill:#4a1515
    style I fill:#1a2f4a
```

---

## Fine-Tuning Pipeline

```mermaid
flowchart TD
    DOCS["📄 Domain documents"] --> INGEST["00:01 ingest_new_docs"]
    INGEST --> PAIRS["00:30 generate_pairs\n72B on DGX (~60–90 min)"]
    PAIRS --> FT["02:30 ft_prepare_chain_run\n14B → 70B → 72B\n(2h buffer after pair gen)"]
    FT --> DEPLOY["05:30 deploy_14b_andrei\nblob-push to PC Andrei Ollama"]
    DEPLOY --> BOT["✅ qwen2.5-aims-ft-vN:latest\nactive on PC Andrei"]
    style PAIRS fill:#1a2f4a
    style FT fill:#1a2f4a
    style BOT fill:#1a4731
```

**Model versioning:** `vN` / `vNrM` — e.g. `v7`, `v7r1`, `v8`, `v8r2`

---

## GPU Cluster Topology

```mermaid
graph LR
    subgraph DGX["DGX Spark  192.168.72.225  —  128 GB VRAM"]
        DGX_MODELS["qwen2.5:72b-instruct-q4_K_M  47 GB\ndeepseek-r1:70b  42 GB\nqwen2.5-coder:32b  20 GB"]
        DGX_DOCKER["Docker Compose — all containers"]
    end
    subgraph PC["PC Andrei  10.77.77.2  —  RTX 4070 16 GB"]
        PC_MODELS["qwen2.5-aims-ft-v7:latest  ~10 GB\nOLLAMA_HOST=0.0.0.0:11434"]
    end
    DGX <-->|"Direct 10 Gbps cable"| PC
    DGX -.->|"LAN fallback 192.168.72.x"| PC
```

**Routing rules:** Small models (14B FT) → PC Andrei only · Two 70B+ models never loaded simultaneously · `OLLAMA_RESOLVE_TTL_SEC=30` prevents 6s latency when DGX unreachable

---

## Technical Reference

### Model Table

| Model | Size | Node | Role |
|-------|------|------|------|
| `qwen2.5-aims-ft-v7:latest` | ~10 GB | PC Andrei | Routing / NLP classify (current FT) |
| `qwen2.5:72b-instruct-q4_K_M` | 47 GB | DGX (cold) | DocAgent rewrite, training pair gen |
| `deepseek-r1:70b` | 42 GB | DGX (cold) | DocAgent reasoning / draft |
| `qwen2.5-coder:32b` | 20 GB | DGX (warm) | Argus diagnostics / code |

### Services & Ports

| Service | Port | Notes |
|---------|------|-------|
| DocAgent API | **8767** | FastAPI, used by Omi + Axi |
| Qdrant | **6333** | Vector DB — RAG |
| LiteLLM Proxy | 4400 | Gemini ×4 keys + Anthropic fallback |
| Grafana | 3000 | DGX monitoring dashboard |
| Task Registry | 8765 | FastAPI CRUD, monitored by Argus |

### Night Schedule

| Time | Task | Note |
|------|------|------|
| 22:30 | VRAM unload | Pre-DocBench cleanup |
| 23:00 | DocBench nightly | Quality test |
| 00:01 | training_ingest | New documents |
| 00:30 | training_generate_pairs | 72B, ~60–90 min |
| **02:30** | ft_prepare_chain_run | Shifted from 01:20 — 2h GPU buffer |
| 05:30 | daily_deploy_14b | Push to PC Andrei |

### Key .env Variables

```bash
PC_ANDREY_OLLAMA_URL=http://10.77.77.2:11434        # primary (direct 10G)
PC_ANDREY_OLLAMA_URL_FALLBACK=http://192.168.72.134:11434
OLLAMA_RESOLVE_TTL_SEC=30                            # resolve cache
QWEN_PC_ASSIST_WARM_ON_TELEGRAM=0                   # no redundant warm-up
DGX_HEAVY_MODEL=qwen2.5:72b-instruct-q4_K_M
DGX_SECOND_HEAVY_MODEL=deepseek-r1:70b
LITELLM_BASE_URL=http://axiomsphere-litellm:4400
```

### Deploy

```bash
docker compose --profile telegram-bots up -d
docker compose restart argus-bot omi-bot axi-bot
```

---

## Standards

| Standard | Coverage |
|----------|----------|
| **ISO 55001:2024** | Asset management — requirements (primary schema) |
| **ISO 55002:2018** | Asset management — implementation guidelines |
| **ISO 45001** | Occupational health & safety |
| **ISO 21502:2020** | Project management guidance |
| **IEC/IEEE 82079-1** | Technical documentation |
| **API RP 505** | Fire protection for refineries |

*ISO standards serve as credibility anchors and compliance scoring targets — not as the core product message.*

---

## Audit Change Log — 2026-04-24

| # | Change | Impact |
|---|--------|--------|
| A | Removed `gpus` from `ocr-watcher` / `omi-register` (CPU-only) | Freed DGX VRAM for models |
| B | `pre_docbench_unload.py` + 22:30 step in night schedule | No VRAM collision before DocBench |
| C | `ollama_resolve.py` tries PC Andrei first, DGX as fallback | Eliminated 6s DGX-timeout latency |
| D–E | `weekly_model_upgrade.py` + `daily_deploy_14b` support `vNrM` versioning | Clean v7r1, v7r2, v8… deploys |
| F | PC Andrei: `OLLAMA_HOST=0.0.0.0:11434` (machine env) | Small model reachable from DGX |
| G | `chat_intent_router.py` — NLP free-text → slash command module | No more missed free-text commands |
| H | Intent router wired into all 3 bots (Argus 18, Omi 12, Axi 3 cmds) | All bots understand natural language |
| I | `OLLAMA_RESOLVE_TTL_SEC=30` | Resolve cache — no more 6s delays |
| J | `QWEN_PC_ASSIST_WARM_ON_TELEGRAM=0` | Stops redundant warm-up API calls |
| K | FT chain 01:20 → **02:30** | 2h GPU buffer after pair generation |
| L | `set_andrei_direct_cable_private.ps1` (Windows Task Scheduler) | Ethernet profile survives reboot |

---

## Roadmap Visual

![AIMS Roadmap 2028](docs/axiompshere_roadmap_2028_final.svg)

---

## Repository Layout

```
AxiOMSphere/
├── README.md
├── LICENSE                      (Apache-2.0)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEMO_SCENARIO.md
│   ├── STANDARDS_MAPPING.md
│   └── EMAILS_STARTUP_CREDITS.md
├── examples/
│   └── doc_agent_example.py
└── docker-compose.yml           (evaluation setup)
```

---

## Grant Applications

We are seeking cloud credits and startup program support:

| Program | Status | What we need |
|---------|--------|--------------|
| [Google for Startups Cloud](https://cloud.google.com/startup) | Applying | GPU compute for inference |
| [Microsoft Founders Hub](https://foundershub.startups.microsoft.com/) | Applying | Azure credits |
| [OpenAI Startup Program](https://openai.com/startups) | Applying | API credits |
| [NVIDIA Inception](https://www.nvidia.com/en-us/startups/) | Applying | DGX access / support |

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
