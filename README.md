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
- Complience agent: standart's identification by context (allocation for ISO55001/55002)
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

Stage 4 — Compliance gate: NVIDIA NIM (OmniRoute · project1)  (~15 sec)
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
        dual_pipeline=True,   # Draft → Rewrite → NIM quality gate
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
        Axi["📄 Axi Bot\nDocument generation\nNVIDIA NIM scoring\n✅ Production"]
        Omi["🗄️ Omi Bot\nDocument registry\nOCR pipeline · RAG\n✅ Production"]
        Argus["📊 Argus Bot\nInfra monitor · Scheduler\nTraining loop supervision\n✅ Production"]
    end

    subgraph "Doc Generation Pipeline — Production ✅"
        Qwen["axi_omi_sphere\nqwen3:32b-q8_0\nDraft + rewrite · DGX Spark"]
        NIM["NVIDIA NIM\nOmniRoute · project1\nISO compliance score · 0.0–1.0"]
    end

    subgraph "Self-Healing Layer — Production ✅"
        Watchdog["🔍 Watchdog Agent\nHealth aggregator · stability score"]
        Repairman["🔧 RepairmanAPI\nDiagnosis + auto-repair"]
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
    Axi -->|"doc request"| R1 --> Qwen --> NIM
    NIM -->|"score + feedback"| Qwen
    Qwen -->|"Final .docx"| TG
    NIM -->|"score ≥ 0.8 → saved"| TRN
    Omi --> AR
    Argus -.->|"monitor + schedule"| Axi & Omi & Qwen
    Argus -.->|"health events"| Repairman
    Watchdog -.->|"stability gate"| Repairman
    AR -.-> NR
    NP -.->|"gates"| NM
    NL -.->|"orchestrates"| NP & NM & NR

    style Axi fill:#0d2137,stroke:#29b6f6,color:#e0f7fa
    style Omi fill:#0d2137,stroke:#4dd0e1,color:#e0f7fa
    style Argus fill:#0d2137,stroke:#81c784,color:#e0f7fa
    style Watchdog fill:#0d2137,stroke:#ffd54f,color:#fff8e1
    style Repairman fill:#0d2137,stroke:#ff8a65,color:#fbe9e7
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
| **Draft** | axi_omi_sphere (qwen3:32b-q8_0) | ISO-aware reasoning, structural outline | ~3 min |
| **Rewrite** | axi_omi_sphere (qwen3:32b-q8_0) | Professional formatting, terminology | ~2 min |
| **Score** | NVIDIA NIM (OmniRoute · project1) | Compliance 0.0–1.0, gap feedback | ~15 sec |
| **Revise** | axi_omi_sphere (qwen3:32b-q8_0) | Targeted fix per score feedback | ~2 min |

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

These feed the nightly fine-tuning pipeline (14B → 32B), so the system improves as it operates.

---

## Agent Architecture — 7 Types

```mermaid

flowchart TD
    HEADER["🏭 AxiOMSphere — Agent & Bot Registry<br/>NemoClaw + Claude Code Architecture"]

    HEADER --> A0 & A1 & A2 & A3 & A4 & A5 & A6 & A7 & A8

    A0["📨 AxiClient<br/>Axi Bot<br/>─────────────────<br/>Thin Telegram client<br/>Receives user documents / commands<br/>Creates tasks in AIMS API /  TaskQueue<br/>Returns task_id and final result<br/>❌ No orchestration<br/>❌ No direct model calls<br/>✅ Phase 0A"]

    A1["🧠 LogiOrchestrator<br/>Logi Bot / Claude Code<br/>─────────────────<br/>Main orchestration brain<br/>Claude Code + Nemotron 3 Super 120B<br/>Plans workflows via Tool Registry<br/>Calls agents/tools through NemoClaw sandbox<br/>Coordinates document, repair, learning loops<br/>✅ Phase 0A Critical"]

    A2["📄 DociAgent<br/>Doci Bot<br/>─────────────────<br/>Document generation and classification<br/>DOCX / XLSX / Markdown processing<br/>Uses router + local models<br/>Escalates low confidence to validation<br/>Stores approved output to Master DB<br/>✅ Phase 0"]

    A3["🗄️ OmiAgent<br/>Omi Bot<br/>─────────────────<br/>Archive, OCR, registry, SSoT<br/>Document registration and deduplication<br/>aims_registry.db / master_documents.db<br/>Owns document lifecycle records<br/>Always active registry service<br/>✅ Phase 0"]

    A4["🔍 KnomiAgent<br/>Knomi Bot<br/>─────────────────<br/>Semantic search and knowledge memory<br/>Vector index over standards and registry<br/>Qdrant + embeddings: nomic / BGE<br/>Provides RAG context to all agents<br/>Feeds examples/context to training loop<br/>✅ Phase 1"]

    A5["📊 ArgusAgent<br/>Argus Bot<br/>─────────────────<br/>KPI, health, queue and telemetry monitor<br/>Collects latency / VRAM / errors / queue depth<br/>Emits HealthEvents and FailureEvents<br/>Verifies repair outcomes<br/>❌ Does not execute repair<br/>✅ Phase 1"]

    A6["🔐 PoliAgent<br/>Poli Bot<br/>─────────────────<br/>Policy, permissions, MoC and approvals<br/>Owns sandbox access rules<br/>Approves or blocks dangerous actions<br/>Controls document ownership and change gates<br/>Blocking safety gate before repair/deploy<br/>✅ Phase 1-2"]

    A7["🔧 MainyRepairAgent<br/>Mainy Bot<br/>─────────────────<br/>Self-repair execution agent<br/>Runs approved repair actions only<br/>restart_container / switch_model / clear_queue<br/>Executes through NemoClaw / OpenShell sandbox<br/>Requires PoliAgent for restricted actions<br/>✅ Phase 2"]

    A8["🎓 TrainiAgent<br/>Traini Bot<br/>─────────────────<br/>Self-learning and model improvement<br/>Collects training pairs and corrections<br/>Runs FT pipeline, eval, canary and promotion<br/>Uses cloud teacher models for hard cases<br/>Updates router/model versions safely<br/>✅ Phase 3-4"]

    A1 -->|"orchestrates"| A2
    A1 -->|"orchestrates"| A3
    A1 -->|"queries"| A4
    A1 -->|"reads events"| A5
    A1 -->|"asks approval"| A6
    A1 -->|"orders repair"| A7
    A1 -->|"triggers learning"| A8

    A0 -->|"creates task"| A1
    A2 -->|"registers approved docs"| A3
    A2 -->|"requests context"| A4
    A2 -->|"low confidence cases"| A8
    A5 -->|"health/failure event"| A1
    A6 -->|"policy decision"| A7
    A7 -->|"repair outcome"| A5
    A8 -->|"new model candidate"| A1
    A8 -->|"training data request"| A4

    style HEADER fill:#0d1117,stroke:#58a6ff,color:#e6edf3
    style A1 fill:#1f2937,stroke:#facc15,color:#f9fafb
    style A0 fill:#111827,stroke:#38bdf8,color:#f9fafb
    style A6 fill:#111827,stroke:#fb7185,color:#f9fafb
    style A7 fill:#111827,stroke:#f97316,color:#f9fafb
    style A8 fill:#111827,stroke:#22c55e,color:#f9fafb

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
        P1["📄 Axi Bot · DocAgent\nQwen3:32b-q8_0 → NIM scoring gate\nRouting model: fine-tuned v6 ✅\nOmi action classifier v15: 100% eval ✅\nTarget: ISO score ≥ 0.85 · < 10 min"]
        P2["🗄️ Omi Bot · DBAgent\nOCR pipeline + document registry\nRAG semantic search\nTarget: retrieval precision ≥ 90%"]
        P3["📊 Argus Bot · SysDog\nDevOps monitor + queue scheduler\nTraining loop gold/DPO pairs\nTarget: uptime ≥ 99.5% · MTTR < 5 min"]
        P4["🔧 Self-Healing Layer\n7 specialised agents (diagnosis · repair · gates)\nAutonomy Control Plane v1 ✅\n5/5 consecutive autonomous runs certified"]
    end

    START --> PROD

    PROD --> GATE1{{"🔒 Gate 1\nScore targets met?\nArgus monitoring stable?\nAutonomous runs certified?"}}
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
        N4["🔍 SysRAG\nVector index over document registry\nInter-agent semantic search\nTarget: relevance ≥ 0.90 · < 2 sec"]
    end

    NEXT2 --> GATE3{{"🔒 Gate 3\nAll 7 agents integrated?\nOrchestrator routing stable?"}}
    GATE3 -->|"✅ Pass"| DONE

    subgraph TUNE["🔄 Continuous Tuning"]
        T1["Routing model v6\n6 cycles ✅ baseline"] --> T2["Routing model v7\nPC node · active 🔄"]
        T2 --> T3["qwen3:32b fine-tune\nnext cycle 🔜"]
        T3 -.->|"scoring"| T4["NVIDIA NIM Gate\nOmniRoute · project1\n0.0–1.0 calibration"]
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
    Dual pipeline Qwen to NIM scoring                         :done, p2a, 2026-03-01, 2026-04-30
    Fine tuning loop gold set and DPO                         :active, p2b, 2026-04-01, 2026-06-30
    Self-healing layer and Autonomy Control Plane v1          :done, p2sh, 2026-05-01, 2026-05-13
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

## Autonomy Control Plane v1 — Certified

**Status: `READY_FOR_AUTONOMOUS_OPERATION_WITH_TASK_LEDGER_V1`**

As of 2026-05-13, AxiOMSphere passed **5/5 consecutive autonomous task runs** without manual intervention, certifying the Autonomy Control Plane v1:

| Run | Task Type | Result | Time |
|-----|-----------|--------|------|
| 1 | Readiness / status check | ✅ PASS | ~2 s |
| 2 | DocAgent dry-run generation | ✅ PASS | ~3 s |
| 3 | Knomi RAG — 3 semantic queries | ✅ PASS | ~4 s |
| 4 | Document anonymization | ✅ PASS | ~5 s |
| 5 | Cloud teacher scoring (NIM) | ✅ PASS | ~7 s |

Each run: accept task → create run_id → agent chain → TaskLedger → Argus watchdog check → repair/retry loop (up to 5 attempts) → Telegram delivery.

The **Self-Healing Layer** runs 7 specialised agents providing automated diagnosis, repair approval, security gating, and health aggregation — all operating without human intervention.

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
        C -->|"NIM Quality Gate\nISO 45001 · ISO 21502 · IEC 82079"| D{"Score ≥ 80%?"}
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
    INGEST --> PAIRS["00:30 generate_pairs\n32B on DGX (~60–90 min)"]
    PAIRS --> FT["02:30 ft_prepare_chain_run\n14B → 32B\n(2h buffer after pair gen)"]
    FT --> DEPLOY["05:30 daily_deploy\nblob-push to secondary node"]
    DEPLOY --> BOT["✅ Fine-tuned model vN:latest\nactive on secondary node"]
    style PAIRS fill:#1a2f4a
    style FT fill:#1a2f4a
    style BOT fill:#1a4731
```

**Model versioning:** `vN` / `vNrM` — e.g. `v7`, `v7r1`, `v8`, `v8r2`

**Fine-tuning status (2026-05):**

| Run | Model | Dataset | Eval (golden_v2) |
|-----|-------|---------|------------------|
| v15 | Qwen2.5-14B QLoRA | v10 (754 samples) | **14/14 — 100%** ✅ |
| qwen3-8b-v1 | Qwen3-8B QLoRA | v9 | 2/15 — 13% ❌ |

---

## GPU Cluster Topology

```mermaid
graph LR
    subgraph DGX["Primary Node — 128 GB VRAM · Redundant network"]
        DGX_MODELS["qwen3:32b-q8_0 (axi_omi_sphere)  ~34 GB\nqwen2.5-coder:32b  20 GB\nDocker Compose — all production containers"]
        DGX_DOCKER["NIM OCR · LiteLLM · Task Registry\nOmi · Axi · Argus bots\nSelf-Healing Layer"]
    end
    subgraph PC["Secondary Node — RTX 4070 16 GB"]
        PC_MODELS["Fine-tuned routing model v7  ~10 GB\nOllama local inference"]
    end
    DGX <-->|"Direct high-speed link"| PC
    DGX -.->|"LAN fallback"| PC
```

**Routing rules:** Small models (14B FT) → secondary node only · Two 32B+ models never loaded simultaneously

---

## Technical Reference

### Model Table

| Model | Size | Node | Role |
|-------|------|------|------|
| `axi_omi_sphere` (qwen3:32b-q8_0) | ~34 GB | Primary (warm) | DocAgent — draft, rewrite, revision |
| `qwen2.5-coder:32b` | 20 GB | Primary (warm) | Argus diagnostics / code / chat |
| `omi-ft-14b-v15` (Qwen2.5-14B QLoRA) | ~10 GB | Primary | Omi action classifier — **100% eval (14/14)** ✅ |
| Routing model v6 (qwen2.5 FT) | ~10 GB | Primary | Intent routing — Omi, Axi, Argus |
| Routing model v7 (qwen2.5 FT) | ~10 GB | Secondary | Small model — routing fallback |
| Nemotron 3 Super 120B | ~100 GB | Primary | Repairman — autonomous code repair |

### Night Schedule

| Time (UTC) | Task | Note |
|------|------|-------|
| 22:30 | VRAM unload | Pre-DocBench cleanup |
| 23:00 | DocBench nightly | Quality test |
| 00:01 | training_ingest | New documents |
| 00:30 | training_generate_pairs | 32B, ~60–90 min |
| **02:30** | ft_prepare_chain_run | Shifted 2h — GPU buffer after pair gen |
| 05:30 | daily_deploy_14b | Push to secondary node |

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

### 2026-05 (May)

| # | Change | Impact |
|---|--------|--------|
| M | Gemini → NVIDIA NIM migration | All scoring now runs on-premise via OmniRoute; zero active Gemini calls |
| N | Self-healing agent cluster deployed (7 specialised agents) | Automated diagnosis, repair, and policy gating without manual intervention |
| O | Autonomy Control Plane v1 certified — 5/5 runs PASS | System status: `READY_FOR_AUTONOMOUS_OPERATION_WITH_TASK_LEDGER_V1` |
| P | `omi-ft-14b-v15` QLoRA — 100% eval (14/14 golden_v2) | Omi action classifier fully converged on v10 dataset (754 samples) |
| Q | Nemotron 3 Super 120B added as Repairman model | Autonomous code repair via Claude Code proxy gateway |
| R | TaskLedger v1 — per-run JSON ledger with repair/retry loop | Up to 5 repair attempts per step; full audit trail persisted |

### 2026-04 (April)

| # | Change | Impact |
|---|--------|--------|
| A | Removed GPU requirement from OCR watcher (CPU-only) | Freed primary node VRAM for inference models |
| B | VRAM unload step added to nightly schedule | No VRAM collision before DocBench |
| C | Resolver tries secondary node first, primary as fallback | Eliminated 6s timeout latency |
| D–E | Model versioning supports `vNrM` format | Clean v7r1, v7r2, v8… deploys |
| F | Secondary node Ollama accessible from primary over LAN | Small model routing works cross-node |
| G | NLP intent router — free-text → slash command | No more missed free-text commands |
| H | Intent router wired into all 3 bots (Argus 18, Omi 12, Axi 3 cmds) | All bots understand natural language |
| I | Resolve cache added | Prevents repeated resolution delays |
| J | Redundant warm-up calls disabled | Stops unnecessary secondary node load |
| K | FT chain shifted from 01:20 → **02:30** | 2h GPU buffer after pair generation |
| L | Ethernet profile persistence script (Windows Task Scheduler) | Direct link survives reboot |

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

- 📧 hello@axiomsphereai.com
- 🌐 [Website](https://axiomsphereaassistanceaims.github.io/AIMS-Agent-Orchestrator/)
- 💼 [LinkedIn](https://www.linkedin.com/in/evgeny-shokk-54781716)

---

## License

[Apache License 2.0](LICENSE)

> Built on open-source: Python · Ollama · Qwen3 · Qwen2.5 · NVIDIA NIM · Anthropic Claude · python-telegram-bot · python-docx · NIM OCR

---

*End of document*
