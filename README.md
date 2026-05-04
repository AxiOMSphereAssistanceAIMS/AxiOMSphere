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
User request → Planning → Draft (Qwen3-32B) → Rewrite (Qwen3-32B) → Score (Gemini + Claude) → Revise → Register → Notify
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
3. Benchmark admin 14B / coding 32B/ logical 32B/ fine formating 32B quality vs. the highest documents tuned cloud model tradeoffs
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

Stage 2 — Draft agent: axi_omi_sphere (qwen3:32b-q8_0)   (~3 min)
  → Generates structured draft with ISO 10013 / ISO/IEC Directives-aware section headers
  → Produces hazard table with risk matrix, elimination → substitution → PPE controls

Stage 3 — Rewrite agent: axi_omi_sphere (qwen3:32b-q8_0)     (~2 min)
  → Professional formatting, paragraph cohesion, terminology standardization ISO 2145:1978

Stage 4 — Compliance gate: Gemini Flash / Anthropic Claude  (~15 sec)
  → Score: 0.84 / 1.0
  → Feedback: "Add specific corrections and specification per ....."

Stage 5 — Revision: axi_omi_sphere (qwen3:32b-q8_0)          (~2 min)
  → Target correction applied, assessment re-checked (knowledge base and lessons learned in background)

Output: JSA_confined_space_entry.docx → delivered to Telegram
        ISO compliance: 84%   |   Total time: ~11 min
        Training pair saved → gold_pairs.jsonl (score ≥ 0.8)
```


[🖼 Architecture](docs/ARCHITECTURE.md)
[📺 <video src="docs/demo.mp4" controls width="100%"></video>]                            

https://github.com/user-attachments/assets/84069854-3288-4b8c-96f7-aa70d5362347

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
        Qwen["axi_omi_sphere\nqwen3:32b-q8_0\nDraft + rewrite · DGX Spark"]
        Gemini["Gemini Flash/Pro\n+ Anthropic Claude\nISO compliance score · 0.0–1.0"]
    end

    subgraph "Data Layer — Production ✅"
        AR[("aims_registry.db\nMaster document registry")]
        TRN[("gold_pairs.jsonl\ndpo_pairs.jsonl\nAuto-saved every run")]
    end

    subgraph "Phase 3 — Deployed ✅"
        NL["🧠 Logi Bot\nCross-dept AIMS sync\n✅ Deployed"]
        NP["🔐 Poli Agent\nAccess rights · MoC gate\n✅ Deployed (port 8004)"]
        NM["🔧 Mainy Agent\nMaintenance automation\n✅ Deployed (port 8005)"]
        NR["🔍 Knomi Agent\nSemantic memory · RAG\n✅ Deployed (port 8002)"]
    end

    TG --> Axi & Omi
    Axi -->|"doc request"| Qwen --> Gemini
    Gemini -->|"score + feedback"| Qwen
    Qwen -->|"Final .docx"| TG
    Gemini -->|"score ≥ 0.8 → saved"| TRN
    Omi --> AR
    Argus -.->|"monitor + schedule"| Axi & Omi & Qwen
    AR -.-> NR
    Argus -.-> NM
    NP -.->|"gates"| NM
    NL -.->|"orchestrates"| NP & NM & NR

    style Axi fill:#0d2137,stroke:#29b6f6,color:#e0f7fa
    style Omi fill:#0d2137,stroke:#4dd0e1,color:#e0f7fa
    style Argus fill:#0d2137,stroke:#81c784,color:#e0f7fa
    style NL fill:#003300,stroke:#66bb6a,color:#c8e6c9
    style NP fill:#003300,stroke:#4ade80,color:#c8e6c9
    style NM fill:#003300,stroke:#4ade80,color:#c8e6c9
    style NR fill:#003300,stroke:#4ade80,color:#c8e6c9
```

---

## How It Works

### Doc Generation Pipeline

| Stage | Model | Role | Time |
|-------|-------|------|------|
| **Draft** | axi_omi_sphere (qwen3:32b-q8_0) | ISO-aware reasoning, structural outline | ~3 min |
| **Rewrite** | axi_omi_sphere (qwen3:32b-q8_0) | Professional formatting, terminology | ~2 min |
| **Score** | Gemini Flash/Pro + Anthropic Claude | Compliance 0.0–1.0, gap feedback | ~15 sec |
| **Revise** | axi_omi_sphere (qwen3:32b-q8_0) | Targeted fix per score feedback | ~2 min |

Quality gate: <60% → reject + retry · ≥60% → accepted · target **98% compliance**

### NLP Intent Routing

All bots use a local fine-tuned model (`chat_intent_router.py`) to classify free-text messages into slash commands **before** any cloud LLM call — keeping latency low and cloud costs minimal:

```
"check if DGX is up"  →  /dgx status
"show stuck tasks"    →  /tasks --stuck
"generate MOC doc"    →  /doc --type=moc
```

Keyword fallback (`_keyword_classify`) activates automatically when the PC Andrei small model is offline — no cloud calls needed for common commands.

### Cross-Bot Handoff

Inter-agent message passing uses **Redis as primary transport** (`AIMS_REDIS_URL`), with SQLite as graceful fallback when Redis is unavailable:

```
enqueue_handoff() → Redis RPUSH handoff:{target}  [primary]
                 → SQLite cross_bot_handoff table  [fallback]
claim_pending_for_target() → Redis LPOP (atomic)  [primary]
                          → SQLite poll            [fallback]
```

In-flight tracking via `handoff:inflight:{id}` (1h TTL) enables automatic re-queue on failure without changing the public API.

### Continuous Training Loop

Every production run auto-saves training pairs — no opt-in flag needed:
- `gold_pairs.jsonl` — document + task pairs scoring ≥ 0.8
- `dpo_pairs.jsonl` — preference pairs for RLHF (DPO trainer, `ops/ft/scripts/dpo_train.py`)

These feed the nightly fine-tuning pipeline (14B → 32B), so the system improves as it operates.

---

## Agent Architecture — 7 Types

```mermaid
flowchart TD
    HEADER["🏭 AxiOMSphere — Agent Type Registry"]

    HEADER --> T1 & T2 & T3 & T4 & T5 & T6 & T7

    T1["📄 DocAgent\nDoci Bot\n─────────────────\nCorporate document generation\nQwen-32B → Qwen-32B\n→ Cloud AI ISO scoring ≥ 80%\n⚡ Parallel per department\n✅ Production"]

    T2["🗄️ DBAgent\nOmi Bot\n─────────────────\nDocument archive · OCR pipeline\nRAG semantic memory\nSingle Source of Truth\naims_registry.db\n🔄 Always active\n✅ Production"]

    T3["📊 SysDog\nArgus Bot\n─────────────────\nKPI collection & monitoring\nScheduler · Queue orchestration\nFailure analysis · Model tuning\nTraining loop supervision\n🔄 Continuous\n✅ Production"]

    T4["🧠 SysLogicArh\nLogi Bot\n─────────────────\nLogic & synchronization\nCross-dept AIMS alignment\nFunctional interface mapping\nSAMP adherence verification\n⚡ Parallel per process\n✅ Deployed (Phase 3)"]

    T5["🔐 SysPolic\nPoli Bot\n─────────────────\nAccess rights & permissions\nDocument ownership registry\nMoC control & registration\nSecurity policy enforcement\n🔒 Blocking gate\n✅ Deployed (port 8004)"]

    T6["🔧 SysMR\nMainy Bot\n─────────────────\nReceives repair scripts from SysDog\nExecutes fixes & patches\nScheduled maintenance tasks\nRequires SysPolic approval\n⚡ Scheduled / on-demand\n✅ Deployed (port 8005)"]

    T7["🔍 SysRAG\nKnomi Bot\n─────────────────\nSemantic search for all agents\nVector index over aims_registry\nEmbedding: nomic / BGE\n🔄 Background / on-demand\n✅ Deployed (port 8002)"]

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
        P1["📄 Axi Bot · DocAgent\nQwen3:32b-q8_0 → Gemini/Claude gate\nqwen2.5-aims-ft-v6: routing ✅\nqwen3:32b: fine-tuning in progress 🔄\nTarget: ISO score ≥ 0.85 · < 10 min"]
        P2["🗄️ Omi Bot · DBAgent\nOCR pipeline + aims_registry.db\nRAG semantic search\nomi-ft-14b-v15: 100% on golden_v2 ✅\nTarget: retrieval precision ≥ 90%"]
        P3["📊 Argus Bot · SysDog\nDevOps monitor + queue scheduler\nTraining loop gold/DPO pairs\nTarget: uptime ≥ 99.5% · MTTR < 5 min"]
    end

    START --> PROD

    PROD --> GATE1{{"🔒 Gate 1\nScore targets met?\nArgus monitoring stable?"}}
    GATE1 -->|"✅ Pass"| NEXT1

    subgraph NEXT1["✅ DEPLOYED — Phase 3 (2026-05-04)"]
        N1["🧠 SysLogicArh\nLogi Bot — AIMS sync engine\nCross-dept coherence · Telegram bot\nTarget: 0 logic conflicts in 100 docs"]
        N2["🔐 SysPolic\nPoli Agent — rights & permissions\nMoC registration · port 8004\nTarget: 100% MoC compliance · 0 breaches"]
        N3["🔧 SysMR\nMainy Agent — repair executor\nScript execution + rollback · port 8005\nRequires SysPolic approval"]
        N4["🔍 SysRAG\nKnomi Agent — semantic search\nVector index over aims_registry · port 8002\nTarget: relevance ≥ 0.90 · < 2 sec"]
    end

    NEXT1 --> GATE2{{"🔒 Gate 2\nLogicArh coherence ≥ 95%?\nSysPolic 0 access breaches?"}}
    GATE2 -->|"❌ Fail"| FIX2["🔧 RCA Loop"]
    FIX2 --> GATE2
    GATE2 -->|"✅ Pass"| GATE3

    GATE3{{"🔒 Gate 3\nAll 7 agents integrated?\nOrchestrator routing stable?"}}
    GATE3 -->|"✅ Pass"| DONE

    subgraph TUNE["🔄 Continuous Tuning"]
        T1["qwen2.5-aims-ft-v6\n6 cycles ✅ routing baseline"] --> T2["omi-ft-14b-v15\n100% eval ✅ action classifier"]
        T2 --> T3["qwen3:8B-v2\nfixes timeout errors 🔄"]
        T3 -.->|"scoring"| T4["Gemini / Claude Gate\n0.0–1.0 calibration"]
    end
    TUNE -.-> FIX2

    DONE(["✅ AxiOMSphere FULLY OPERATIONAL\n7 Agents · ISO 55001 Compliant"])

    style PROD fill:#003300,stroke:#66bb6a,color:#c8e6c9
    style NEXT1 fill:#003300,stroke:#4ade80,color:#c8e6c9
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
    Dual pipeline to Qwen to Gemini scoring                   :done, p2a, 2026-03-01, 2026-04-30
    Fine tuning loop gold set and DPO                         :active, p2b, 2026-04-01, 2026-06-30
    Model quality calibration and evaluator alignment         :active, p2c, 2026-07-01, 2026-08-31
    Gate B Model quality and safety                           :active, gB, 2026-09-01, 2026-09-02

    section Phase 3 - Agent Mesh
    SysLogicArch cross agent logic and sync build             :done, p3a, 2026-05-04, 2026-05-04
    SysPolicy rights ownership approval build                 :done, p3b, 2026-05-04, 2026-05-04
    SysMR maintenance and repair guardrails build             :done, p3c, 2026-05-04, 2026-05-04
    SysRAG semantic memory and retrieval build                :done, p3d, 2026-05-04, 2026-05-04
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
    style L6 fill:#f9f,stroke:#333,stroke-width:2px
    classDef default fill:#40E0D0,stroke:#000,stroke-width:2px,color:#000;
```

---

## Document Generation — Agent Structure

```mermaid
graph TD
    subgraph "Phase 1 — Engineer Assistant"
        A[Individual Engineer] -->|Natural language request| B("AI Document Assistant\nAxi Bot")
        B -->|"Qwen-32B dual pipeline"| C[Structured Document Draft]
        C -->|"Cloud Quality Gate\nISO 45001 · ISO 21502 · IEC 82079"| D{"Score ≥ 80%?"}
        D -->|Yes| E["✅ Approved Document .docx"]
        D -->|No| F[Qwen revises with recommendations]
        F --> D
    end
    E --> L["Master Document Registration\nin aims_registry.db"]

    style B fill:#c084fc,stroke:#7e22ce,stroke-width:2px,color:#fff
    style E fill:#4ade80,stroke:#166534,stroke-width:2px
    style L fill:#60a5fa,stroke:#1d4ed8,stroke-width:2px
    classDef default fill:#40E0D0,stroke:#000,stroke-width:2px,color:#000;
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
    H --> I["DocAgent — Qwen 32B DGX"]
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
    PAIRS --> FT["02:30 ft_prepare_chain_run\n14B → 32B\n(2h buffer after pair gen)"]
    FT --> DEPLOY["05:30 deploy_14b_andrei\nblob-push to PC Ollama"]
    DEPLOY --> BOT["✅ qwen2.5-aims-ft-vN:latest\nactive on PC Andrei"]
    style PAIRS fill:#1a2f4a
    style FT fill:#1a2f4a
    style BOT fill:#1a4731
```

**Model versioning:** `vN` / `vNrM` — e.g. `v7`, `v7r1`, `v15`, `v15r1`

### Fine-Tuning Status (2026-05)

| Run | Model | Dataset | Eval (golden_v2, 14 cases) | Notes |
|-----|-------|---------|----------------------------|-------|
| v15 | Qwen2.5-14B QLoRA | v10 (754 samples) | **14/14 — 100%** ✅ | Omi action classifier — production |
| qwen3-8b-v1 | Qwen3-8B QLoRA | v9 | 2/15 — 13% ❌ | 7× TimeoutError (thinking mode on at train time) + 6 routing errors |
| qwen3-8b-v2 | Qwen3-8B QLoRA | v10 | In progress 🔄 | `enable_thinking: false` — config fixed |

DPO pairs: `ops/ft/scripts/dpo_train.py` — 22 pairs ready, TRL DPOTrainer, 4-bit QLoRA.

---

## GPU Cluster Topology

```mermaid
graph LR
    subgraph DGX["DGX Spark — 128 GB VRAM"]
        DGX_MODELS["qwen3:32b-q8_0 (axi_omi_sphere)  ~34 GB\nqwen2.5-coder:32b  20 GB\nomi-ft-14b-v15  ~10 GB\nDocker Compose — all 21 containers"]
        DGX_DOCKER["Task Registry · Qdrant · Redis · LiteLLM\nOmi · Axi · Argus · Logi · Poli · Mainy · Knomi"]
    end
    subgraph PC["PC Andrei — RTX 4070 16 GB"]
        PC_MODELS["qwen2.5-aims-ft-v7:latest  ~10 GB\nOLLAMA_HOST=0.0.0.0:11434"]
    end
    DGX <-->|"Direct 10 Gbps cable"| PC
    DGX -.->|"LAN fallback (router IP)"| PC
```

**Routing rules:** Small models (14B FT) → PC only · Two 32B+ models never loaded simultaneously on DGX · `nemotron-3-super:120b` (~100 GB) loads alone · `OLLAMA_RESOLVE_TTL_SEC=30` prevents 6s latency spikes

---

## Technical Reference

### Running Services (2026-05-04)

| # | Container | Status | Role |
|---|-----------|--------|------|
| 1 | `axiomsphere-aims-redis` | ✅ healthy | Redis queue backbone (`AIMS_REDIS_URL`) |
| 2 | `axiomsphere-qdrant` | ✅ running | Vector DB — standards RAG (port 6333) |
| 3 | `axiomsphere-prometheus` | ✅ running | Metrics collection |
| 4 | `axiomsphere-grafana` | ✅ running | Dashboards (port 3000) |
| 5 | `axiomsphere-task-registry` | ✅ running | Task state API (port 8765) |
| 6 | `axiomsphere-flaresolverr` | ✅ healthy | JS-render proxy for scrapers |
| 7 | `axiomsphere-schedule` | ✅ running | Cron: nightly FT, deploy, etc. |
| 8 | `axiomsphere-inbox-cleanup` | ✅ running | 14-day inbox purge |
| 9 | `axiomsphere-litellm` | ✅ running | LiteLLM proxy — Gemini + Anthropic (port 4400) |
| 10 | `axiomsphere-ocr-watcher` | ✅ running | OCR pipeline (`Dockerfile.ocr-eng`) |
| 11 | `axiomsphere-omi-api` | ✅ running | Omi REST API (port 8765) |
| 12 | `axiomsphere-omi-quality-gate` | ✅ running | Post-OCR quality filter |
| 13 | `axiomsphere-omi-batch-ingest` | ✅ running | Batch document processor |
| 14 | `axiomsphere-doc-agent` | ✅ running | Doc generation API (port 8767) |
| 15 | `axiomsphere-axi-bot` | ✅ running | Main Telegram bot (production) |
| 16 | `axiomsphere-argus-bot` | ✅ healthy | Infra monitor + scheduler |
| 17 | `axiomsphere-omi-bot` | ⚠️ running, not responding | Container up — LLM/queue bug TBD |
| 18 | `axiomsphere-aims-api` | ✅ running | Internal task API (port 8000, internal network) |
| 19 | `axiomsphere-aims-worker` | ✅ running | Redis worker pool (4 threads) |
| 20 | `axiomsphere-aims-orchestrator` | ✅ running | Failure analysis daemon (Redis `queue:orchestrator`) |
| 21 | watchdog-bot (host process) | ✅ running | Outside Docker — monitors all 20 containers |

Scheduled (run on demand via `schedule` container, `restart: 'no'`): `omi-register`, `omi-sync`, `job-filter-bot`.

### Model Table

| Model | Size | Node | Role |
|-------|------|------|------|
| `axi_omi_sphere` (qwen3:32b-q8_0) | ~34 GB | DGX (warm) | DocAgent — draft, rewrite, revision |
| `qwen2.5-coder:32b` | 20 GB | DGX (warm) | Argus diagnostics / code / chat |
| `omi-ft-14b-v15` (Qwen2.5-14B QLoRA) | ~10 GB | DGX | Omi action classifier — **100% on 14/14 golden_v2** |
| `qwen2.5-aims-ft-v6` | ~10 GB | DGX | Intent routing — Omi, Axi, Argus |
| `qwen2.5-aims-ft-v7:latest` | ~10 GB | PC Andrei | Intent routing fallback |
| `nemotron-3-super:120b` | ~100 GB | Ollama → NIM | Repairman (Claude Code proxy, port 8082) — load separately |

**VRAM rule:** never load two 70B+ models simultaneously on DGX (128 GB total). Unload before switching.

### Services & Ports

| Service | Port | Notes |
|---------|------|-------|
| DocAgent API | **8767** | FastAPI, used by Omi + Axi |
| AIMS API | **8000** | Internal task API (internal network only — not exposed to host) |
| Knomi Agent | **8002** | Semantic search / RAG API (127.0.0.1 only) |
| Poli Agent | **8004** | Access rights, MoC gate (127.0.0.1 only) |
| Mainy Repair Agent | **8005** | Maintenance repair executor (127.0.0.1 only) |
| Qdrant | **6333** | Vector DB — RAG |
| LiteLLM Proxy | **4400** | Gemini key + Anthropic fallback |
| Task Registry | **8765** | FastAPI CRUD, monitored by Argus |
| Grafana | **3000** | DGX monitoring dashboard |
| Anthropic Proxy Gateway | **8082** | `ops/gateway/anthropic_proxy.py` → Ollama/NIM |
| Ollama (DGX) | **11434** | Local model inference |

### Night Schedule

| Time UTC | Task | Note |
|----------|------|------|
| 22:30 | VRAM unload (`pre_docbench_unload.py`) | Clears GPU before DocBench |
| 23:00 | DocBench nightly | Quality regression test |
| 00:01 | `training_ingest` | Ingest new documents |
| 00:30 | `training_generate_pairs` | 32B on DGX, ~60–90 min |
| **02:30** | `ft_prepare_chain_run` | Shifted from 01:20 — 2h GPU buffer |
| 05:30 | `daily_deploy_14b` | Push to PC Andrei via Ollama blob |

### Key .env Variables

```bash
PC_OLLAMA_URL=http://<pc-direct-ip>:11434           # primary (direct 10 Gbps)
PC_OLLAMA_URL_FALLBACK=http://<router-ip>:11434     # LAN fallback
OLLAMA_RESOLVE_TTL_SEC=30                            # resolve cache — prevents 6s timeout
AIMS_REDIS_URL=redis://aims-redis:6379               # cross-bot handoff + worker queue
QWEN_PC_ASSIST_WARM_ON_TELEGRAM=0                   # no redundant warm-up
LITELLM_BASE_URL=http://axiomsphere-litellm:4400
NVIDIA_API_KEY=<your-nim-api-key>                   # for cloud scoring via NIM
AIMS_CLAUDE_PROXY_TOKEN=<your-token>                 # gateway auth token
```

### Deploy

```bash
# All services including Phase 3 agents
docker compose --profile telegram-bots up -d

# Restart core bots
docker compose restart argus-bot omi-bot axi-bot

# Start Anthropic proxy gateway (for Claude Code repairman)
bash ops/gateway/start_gateway.sh
```

---

## Claude Code Repairman

Claude Code can run as a project-wide repair agent using the local gateway proxy:

```bash
# Start gateway first
bash ops/gateway/start_gateway.sh

# Connect Claude Code to the gateway
ANTHROPIC_BASE_URL=http://localhost:8082 \
ANTHROPIC_API_KEY=aims-local-repair-token \
claude --model aims-repairman-nemotron
```

Config: `ops/config/claude_code_repair_tool.yaml`. Forbidden operations: `exfiltrate_secrets`, `bypass_poli_in_production`, `delete_production_data`.

---

## Standards

| Standard | Coverage |
|----------|----------|
| **ISO 55001:2024** | Asset management — requirements (primary schema) |
| **ISO 55002:2018** | Asset management — implementation guidelines |
| **IEC/IEEE 82079-1:2019** | Technical documentation |
| **ISO 21502:2020** | Project management guidance |
| **ISO 10013:2021** | Guidelines for Documented Information |
| **ISO 2145** |  Numbering of Divisions and Subdivisions |
| **ISO 9000:2015** | Fundamentals & Vocabulary |
| **ISO 19005** | Document File Format for Long-Term Preservation |
| **ISO 15489** | Information and Documentation - Records Management |

more than international 150 standards, around 1500 master document

*ISO standards serve as credibility anchors and compliance scoring targets — not as the core product message.*

---

## Audit Change Log

### 2026-05-04 — Production Launch Sprint

| # | Change | Impact |
|---|--------|--------|
| 1 | `argus_orchestrator.py` IndentationError fixed | Argus bot stable |
| 2 | `Dockerfile.ocr-eng` created | `ocr-watcher` now builds and runs |
| 3 | `.env` `@aims_watchdog_bot` bare `@` replaced with comment | Docker Compose parses cleanly |
| 4 | `Dockerfile.aims-services` created — shared base for aims-api/worker/orchestrator/Phase 3 agents | All new services start correctly |
| 5 | `aims-api`, `aims-worker`, `aims-orchestrator` moved to correct Dockerfile + PYTHONPATH | No more crash loops |
| 6 | `ops/aims_orchestrator_daemon.py` created — Redis polling daemon | `aims-orchestrator` stays alive |
| 7 | Watchdog fixed — `docker ps --filter status=running` + healthcheck status | No more false "all UP" reports |
| 8 | `omi-bot` token chain collision in docker-compose fixed | Omi bot now processes messages |
| 9 | `logi-bot` added to docker-compose (`telegram-bots` profile) | Cross-dept sync deployed |
| 10 | `poli-agent` added to docker-compose (port 8004, healthcheck) | Access rights gate deployed |
| 11 | `mainy-repair-agent` added to docker-compose (port 8005, requires poli-agent) | Repair executor deployed |
| 12 | `knomi-agent` added to docker-compose (port 8002, healthcheck) | Semantic RAG search deployed |
| 13 | Keyword fallback `_keyword_classify` added to `chat_intent_router.py` | Intent routing works offline |
| 14 | `ops/ft/scripts/dpo_train.py` written — 22 pairs, TRL DPOTrainer, 4-bit QLoRA | DPO training ready |
| 15 | Redis transport added to `cross_bot_handoff.py` (SQLite fallback kept) | Cross-bot queue no longer fragile |
| 16 | `redis>=5.0.1` added to `Dockerfile.axi-bot` + `omi_telegram/requirements.txt` | Both bots can use Redis handoff |
| 17 | `AIMS_REDIS_URL` + `depends_on: aims-redis` added to axi-bot + omi-bot in compose | Redis wired end-to-end |
| 18 | `ops/core/sandbox_runner.py` created — high-level sandbox API over `executor.py` | Code execution ready for agents |
| 19 | Watchdog alert on `running+unhealthy` added to `argus_monitor._loop_containers` | No silent health failures |
| 20 | `omi-ft-14b-v15` trained — 14/14 (100%) on `golden_v2.json` | Omi action classifier production-ready |

### 2026-04-24 — Infrastructure Hardening

| # | Change | Impact |
|---|--------|--------|
| A | Removed `gpus` from `ocr-watcher` / `omi-register` (CPU-only) | Freed DGX VRAM for models |
| B | `pre_docbench_unload.py` + 22:30 step in night schedule | No VRAM collision before DocBench |
| C | `ollama_resolve.py` tries PC first, DGX as fallback | Eliminated 6s DGX-timeout latency |
| D–E | `weekly_model_upgrade.py` + `daily_deploy_14b` support `vNrM` versioning | Clean v7r1, v7r2, v8… deploys |
| F | PC: `OLLAMA_HOST=0.0.0.0:11434` (machine env) | Small model reachable from DGX |
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
├── CLAUDE.md                    # Claude Code project guide
├── PLAN.md                      # Full project roadmap — phases 0–5, current status
├── PROJECT_CONSTITUTION.md      # Invariants — roles, RAG, security, language (append-only)
├── LICENSE                      (Apache-2.0)
├── docker-compose.yml           # All 21 services + Phase 3 agents
├── docker-compose.dgx.yml       # DGX-specific overrides
├── .env.spark.example           # Environment variable template
├── ops/
│   ├── axi_bot.py               # Telegram bot — document generation (~3976 lines)
│   ├── aims_orchestrator_daemon.py  # Redis polling daemon for aims-orchestrator
│   ├── agents/                  # Agent classes: Omi, Argus, Doci, Poli, Mainy, Knomi…
│   ├── argus/                   # Infra monitoring: keepalive, diagnose, orchestrator
│   ├── gateway/                 # Anthropic-compatible proxy → Ollama/NIM (port 8082)
│   │   ├── anthropic_proxy.py   # FastAPI app
│   │   └── start_gateway.sh     # Sources .env BOM-safe, sets model env vars
│   ├── core/                    # Config validator, queue, worker, metrics
│   │   ├── orchestrator.py      # DAG runner — DAG, Step, DAGResult with per-step retry
│   │   └── sandbox_runner.py    # High-level sandbox API wrapping executor.py
│   ├── workers/                 # Pipeline, quality, data, ft_pipeline workers
│   ├── router/                  # local_router, nim_router, fallback_router
│   ├── telegram/                # logi_bot.py (cross-dept sync)
│   ├── ft/                      # Fine-tuning pipeline (QLoRA, GGUF, eval)
│   │   ├── configs/             # train_config_v15.json, qwen3-8b-v2…
│   │   ├── data/                # Datasets (v9, v10, v11…)
│   │   ├── eval/                # golden_v2.json — 14 eval cases (Omi)
│   │   ├── logs/                # Eval results, train logs
│   │   └── scripts/             # build_dataset, train_qlora, eval_actions, dpo_train
│   ├── docagent/                # Doc generation: standards, RAG, NIM scoring
│   ├── omi_telegram/            # OCR register + sync to registry
│   ├── sandbox/                 # executor.py — isolated subprocess code execution
│   ├── scripts/                 # Nightly ops: deploy, upgrade, pre-docbench
│   ├── tests/                   # 26 pytest test files
│   ├── config/                  # Runtime state configs
│   ├── Dockerfile.axi-bot       # Axi bot image (CUDA 12.3, Playwright, redis)
│   ├── Dockerfile.aims-services # Shared base for aims-api/worker/orchestrator/Phase 3
│   ├── Dockerfile.ocr-eng       # English OCR (tesseract-ocr-eng)
│   └── Dockerfile.ocr-rus       # Russian OCR (tesseract-ocr-rus)
├── core/                        # Shared: errors, metrics, queue, route_learn, model_router
└── data/
    └── aims_registry.db         # Master document registry (SQLite)
```

---

## Quick Start

### Prerequisites

- NVIDIA GPU (DGX Spark or equivalent, ≥40 GB VRAM recommended)
- [Ollama](https://ollama.ai) installed and running
- Docker + Docker Compose
- Python 3.11+
- `NVIDIA_API_KEY` (optional — for NIM cloud scoring)

### 1. Clone & configure

```bash
git clone https://github.com/<your-org>/AxiOMSphere.git
cd AxiOMSphere
cp .env.spark.example .env
# Edit .env — fill in PC_OLLAMA_URL, NVIDIA_API_KEY, Telegram bot tokens
# Note: .env has a UTF-8 BOM — Docker Compose handles it; strip manually only if sourcing in bash
```

### 2. Pull models

```bash
ollama pull qwen3:32b-q8_0       # primary draft/rewrite model (~34 GB)
ollama pull qwen2.5-coder:32b    # Argus diagnostics
```

### 3. Start all services

```bash
docker compose --profile telegram-bots up -d
```

### 4. Verify

```bash
docker compose ps
curl -sf http://localhost:8767/health  # DocAgent API
curl -sf http://localhost:8002/health  # Knomi Agent
curl -sf http://localhost:8004/health  # Poli Agent
curl -sf http://localhost:8005/health  # Mainy Agent
```

### 5. Run tests

```bash
export PYTHONPATH=/home/axi_omi_sphere/aims-workspace:$PYTHONPATH
python -m pytest ops/tests/ -v -m "not integration"
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

> Built on open-source: Python · Ollama · Qwen3 · Qwen2.5 · Google Gemini · Anthropic Claude · python-telegram-bot · python-docx · NIM OCR · Redis · Qdrant · Prometheus · Grafana
