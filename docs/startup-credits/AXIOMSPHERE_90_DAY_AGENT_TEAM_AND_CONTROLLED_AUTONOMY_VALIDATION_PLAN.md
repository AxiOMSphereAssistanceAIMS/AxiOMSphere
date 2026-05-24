# AxiOMSphere 90-Day Agent-Team and Controlled Autonomy Validation Plan

**Document type:** External startup-credit development plan  
**Status:** ACTIVE — supersedes `AXIOMSPHERE_90_DAY_VALIDATION_PLAN.md`  
**Prepared:** 2026-05-24  
**Branch:** main (public)  
**Classification:** Public — startup-credit application material

---

## 4.1 Executive Purpose

This plan defines the structured validation work that AxiOMSphere will conduct over a 90-day period, contingent on startup compute credit approval. The validation work targets the transition from a single-operator development workflow to a coordinated agent-team model in which multiple specialist agents share a task registry, accept structured task packages, execute defined capabilities, and return structured result packages — all under human governance at every decision boundary.

The purpose of this validation is not to achieve autonomous operation. The purpose is to produce evidence — systematic, documented, repeatable — that a coordinated agent team can be trusted with progressively scoped capability in an industrial document workflow, and to reach a go/no-go decision on whether controlled autonomy for a bounded class of work-product tasks is appropriate, safe, and technically sustainable.

Compute credits would directly accelerate three bottlenecks that currently limit validation throughput: GPU capacity for sustained generation cycles, vector infrastructure for the knowledge retrieval layer under M2 development, and evaluation API quota for framework-alignment review across multi-agent runs.

---

## 4.2 Starting Point

AxiOMSphere M1 is validated and operating in its development environment. The current applied stage demonstrates:

- Engineer submits a plain-language work-product request
- System generates a structured AIMS work-product draft aligned to applicable ISO 55001 requirements and ISO 55002 guidance
- Draft is reviewed for framework alignment; gap identification and revision guidance are generated
- Draft progresses through structured revision passes; engineer reviews and approves each output before it enters the registry
- Accepted outputs are registered in a local document registry with generation metadata

What is not yet validated:

- Multiple specialist agents operating in a coordinated team on a single task package
- Structured task handoff between agents with defined input/output contracts
- Consistent agent-team behavior across a representative sample of work-product types
- Evidence-based go/no-go criteria for expanding agent-team scope
- Capacity model for sustained agent-team workload

This plan addresses the gap between M1 demonstrated capability and the coordinated agent-team model required for M2 and beyond.

---

## 4.3 Why This Validation Matters for Startup Credit Applications

Startup credit providers evaluating AxiOMSphere need a clear picture of what credits will be used for, what evidence the spend will produce, and what decision the evidence will inform.

Credits support:
- GPU compute for sustained generation and revision cycles across a representative agent-team validation workload
- Vector infrastructure for the M2 controlled knowledge layer — RAG-augmented generation from approved work-product precedents
- Evaluation API quota for framework-alignment review at validation throughput, not development-tier rate limits

Evidence produced:
- Documented task contract definitions for each agent role
- Measured task acceptance, execution, and closure rates across 6 validation levels
- Failure categorisation data for each agent capability gap
- Capacity model calibration — throughput per agent per capability level
- Go/no-go assessment against defined criteria at day 90

Decision informed:
- Whether the coordinated agent-team model is ready for expanded scope in the M2 knowledge layer
- Which agent capabilities require additional development before scope expansion
- What human-governance checkpoints are required at each scope boundary

---

## 4.4 Core Validation Architecture

The validation architecture is named `AGENT_TASK_CONTRACT_AND_CLOSED_LOOP_EXECUTION_ARCHITECTURE`.

It consists of three structural layers:

**Layer 1 — Task Package Contract**  
Every task submitted to an agent is a structured package with defined fields. The contract specifies what an agent must receive before it may begin work, and what it must return when work is complete.

**Layer 2 — Task Lifecycle and State Model**  
Every task passes through a defined set of lifecycle states. No agent may skip a state or transition without meeting the entry condition for the next state. Human approval is a required state for outputs that will enter the registry or inform downstream agent work.

**Layer 3 — Feedback and Learning Loop**  
Every closed task (successfully or with a blocker) produces structured feedback. Failures are categorised against a defined taxonomy. Feedback informs capability development priorities.

These three layers operate within a human governance boundary: no agent-team output becomes a registered work product without qualified engineer review and approval.

---

## 4.5 Agent Responsibility Architecture

The agent team is structured by functional responsibility. Each agent has a defined capability scope, a defined input type it will accept, and a defined output type it will produce.

| Role | Functional Responsibility | Input Accepted | Output Produced |
|------|--------------------------|----------------|-----------------|
| Work-Product Drafting Agent | Generate structured AIMS work-product draft from an accepted task package | Task package (validated, scope-confirmed) | Draft work product + generation metadata |
| Framework-Alignment Review Agent | Review draft against applicable ISO 55001 requirements and ISO 55002 guidance; identify gaps; produce revision guidance | Draft work product + applicable framework reference | Alignment review record + gap list + revision guidance |
| Revision Agent | Apply revision guidance to draft; produce revised version; track revision count | Draft + review record + revision guidance | Revised draft + revision metadata |
| Registry Agent | Accept approved output; register in document registry with full metadata; return registry record | Approved output + engineer approval confirmation | Registry entry + registration confirmation |
| Task Coordination Agent | Route incoming task packages to appropriate specialist agents; monitor lifecycle state; escalate blockers | Incoming task request + context | Routed task package + lifecycle state record |

Agents do not hold authority to accept their own outputs. The framework-alignment review agent reviews drafting-agent outputs; the registry agent accepts only engineer-approved outputs; the task coordination agent escalates — it does not resolve.

---

## 4.6 Task Package Contract

Every task submitted to the agent team must include the following fields before execution begins:

| Field | Description | Required |
|-------|-------------|----------|
| `task_id` | Unique identifier for this task instance | Yes |
| `task_type` | Work-product type (from approved representative categories) | Yes |
| `requestor_id` | Identifier of the engineer who submitted the request | Yes |
| `submitted_at` | ISO 8601 timestamp of submission | Yes |
| `scope_statement` | Plain-language description of what the work product must cover | Yes |
| `applicable_standard` | Primary applicable standard reference (ISO 55001 / ISO 55002 / GFMAM) | Yes |
| `context_documents` | List of approved context documents to reference (may be empty) | Yes |
| `output_format` | Expected output format | Yes |
| `review_required_by` | Engineer responsible for output review and approval | Yes |
| `deadline` | Required completion timestamp | Yes |
| `priority` | Task priority (standard / elevated / critical) | Yes |

A task package missing any required field must be returned to the requestor with a `PACKAGE_INCOMPLETE` status before any agent begins work.

---

## 4.7 Task Input Acceptance Gate

Before an agent begins execution, the task package passes through an input acceptance gate. The gate checks:

1. All required fields are present and non-empty
2. `task_type` is within the agent's defined capability scope for the current validation level
3. `applicable_standard` is within the approved framework references for this validation run
4. `context_documents` are accessible and have been approved (not under active review)
5. `review_required_by` identifies a qualified engineer who has confirmed availability
6. `deadline` is reachable given current agent-team queue depth

If any gate check fails, the task receives status `TASK_REJECTED_AT_INPUT_GATE` with the specific failing check recorded. The task is not attempted. The requestor receives the rejection record and the specific reason.

A task that passes all gate checks receives status `TASK_ACCEPTED` and enters the lifecycle.

---

## 4.8 Controlled Task Lifecycle and Handoff Events

Every task moves through the following lifecycle states. Transitions are events, not polling intervals.

| State | Description | Next States |
|-------|-------------|-------------|
| `TASK_INTENT_CAPTURED` | Request received; pre-validation | `TASK_PACKAGE_ASSEMBLED`, `TASK_REJECTED_INTENT_UNCLEAR` |
| `TASK_PACKAGE_ASSEMBLED` | Task package built; awaiting acceptance gate | `TASK_ACCEPTED`, `TASK_REJECTED_AT_INPUT_GATE` |
| `TASK_ACCEPTED` | Gate passed; task routed to drafting agent | `TASK_DRAFT_IN_PROGRESS` |
| `TASK_DRAFT_IN_PROGRESS` | Drafting agent working | `TASK_DRAFT_COMPLETE`, `TASK_BLOCKED_CAPABILITY_GAP` |
| `TASK_DRAFT_COMPLETE` | Draft produced; routed to review agent | `TASK_REVIEW_IN_PROGRESS` |
| `TASK_REVIEW_IN_PROGRESS` | Review agent assessing framework alignment | `TASK_REVIEW_COMPLETE`, `TASK_BLOCKED_REVIEW_CRITERIA_FAILURE` |
| `TASK_REVIEW_COMPLETE` | Review record produced; revision guidance issued | `TASK_REVISION_IN_PROGRESS`, `TASK_READY_FOR_HUMAN_APPROVAL` |
| `TASK_REVISION_IN_PROGRESS` | Revision agent applying guidance | `TASK_DRAFT_COMPLETE`, `TASK_BLOCKED_REVISION_LIMIT_REACHED` |
| `TASK_READY_FOR_HUMAN_APPROVAL` | Output meets review criteria; awaiting engineer | `TASK_HUMAN_APPROVED`, `TASK_HUMAN_REJECTED_WITH_GUIDANCE` |
| `TASK_HUMAN_APPROVED` | Engineer has approved output | `TASK_REGISTRY_IN_PROGRESS` |
| `TASK_HUMAN_REJECTED_WITH_GUIDANCE` | Engineer has returned output with guidance | `TASK_REVISION_IN_PROGRESS` |
| `TASK_REGISTRY_IN_PROGRESS` | Registry agent recording approved output | `TASK_CLOSED_SUCCESSFULLY`, `TASK_BLOCKED_REGISTRY_FAILURE` |
| `TASK_CLOSED_SUCCESSFULLY` | Output registered; task complete | — |
| `TASK_BLOCKED_CAPABILITY_GAP` | Agent unable to execute; capability gap identified | `TASK_ESCALATED_TO_COORDINATOR` |
| `TASK_BLOCKED_REVIEW_CRITERIA_FAILURE` | Review agent unable to complete; criteria not met | `TASK_ESCALATED_TO_COORDINATOR` |
| `TASK_BLOCKED_REVISION_LIMIT_REACHED` | Maximum revision passes reached without approval | `TASK_ESCALATED_TO_COORDINATOR` |
| `TASK_BLOCKED_REGISTRY_FAILURE` | Registry recording failed | `TASK_ESCALATED_TO_COORDINATOR` |
| `TASK_ESCALATED_TO_COORDINATOR` | Human coordinator notified of blocker | `TASK_CLOSED_WITH_BLOCKER`, `TASK_RESUBMITTED` |
| `TASK_RESUBMITTED` | Coordinator resolved blocker; task re-entered lifecycle | `TASK_ACCEPTED` |
| `TASK_CLOSED_WITH_BLOCKER` | Task closed without successful output; blocker documented | — |
| `TASK_REJECTED_INTENT_UNCLEAR` | Intent too ambiguous to assemble package | — |
| `TASK_REJECTED_AT_INPUT_GATE` | Gate check failed; task not attempted | — |

Every state transition is logged. Every blocked or rejected state produces a structured failure record.

---

## 4.9 Result Package Contract

Every agent returns a structured result package when it completes its stage. The result package is the handoff object between agents and between the agent team and the human review boundary.

| Field | Description |
|-------|-------------|
| `task_id` | Reference to the originating task package |
| `stage` | Which lifecycle stage this result closes |
| `agent_role` | Which agent produced this result |
| `status` | Terminal status for this stage |
| `output_artifact` | The primary output (draft, review record, revised draft, registry entry) |
| `generation_metadata` | Revision count, processing time, applicable standard used |
| `confidence_indicator` | Agent's self-assessed confidence in output completeness (low / medium / high) |
| `gaps_identified` | List of gaps or limitations noted by the agent |
| `review_guidance` | For review-stage results: specific guidance for revision or approval |
| `requires_human_decision` | Boolean — whether a human must act before lifecycle can proceed |
| `escalation_notes` | If blocked: specific description of the blocker for coordinator |

A result package missing `output_artifact` or `status` is invalid and must trigger an immediate `TASK_ESCALATED_TO_COORDINATOR` event.

---

## 4.10 Review, Feedback, Error, and Learning Loop

Every closed task — whether `TASK_CLOSED_SUCCESSFULLY` or `TASK_CLOSED_WITH_BLOCKER` — enters the feedback loop.

**For successful closures:**
- Output quality assessment against applicable framework requirements
- Revision count recorded (how many passes required before human approval)
- Time-in-state recorded for each lifecycle stage
- Agent confidence indicator assessed against actual output quality

**For blocked or failed closures:**
Failure is categorised against the following taxonomy:

| Category | Description |
|----------|-------------|
| `INPUT_PACKAGE_DEFICIENCY` | Task package was incomplete or ambiguous; gate check should have caught it |
| `CAPABILITY_EXECUTION_DEFICIENCY` | Agent attempted the task but produced output below acceptance threshold |
| `SKILL_GAP` | Task type or scope is outside agent's current validated capability |
| `TOOL_OR_RESOURCE_GAP` | Agent lacked access to required tool or resource |
| `INTERFACE_CONFLICT` | Handoff between agents produced a format or protocol mismatch |
| `REVIEW_CRITERIA_FAILURE` | Review agent could not assess output against framework criteria |
| `GOVERNANCE_OR_AUTHORITY_CONFLICT` | Task required a decision that no agent is authorised to make |
| `HUMAN_APPROVAL_REQUIRED` | Output reached human review and was returned with guidance — not a failure, a normal cycle event |

Failure records accumulate in a structured log. At the end of each 30-day period, the failure log is reviewed to identify the most frequent failure categories. Development priorities for the next period are updated based on this review.

Learning is not automatic. No agent updates its behavior from the feedback loop without a human development decision to incorporate the learning. This is a design constraint, not a limitation — it maintains human control over capability development.

---

## 4.11 Conflict Resolution and Decision Governance

When a conflict arises in the agent-team workflow, the resolution pathway follows a defined governance chain:

**Level 1 — Agent self-resolution:** If an agent encounters an ambiguity within its defined capability scope, it applies defined resolution rules. Resolution rules are defined before validation begins, not inferred at runtime.

**Level 2 — Task coordinator escalation:** If the agent cannot resolve within its rules, the task escalates to the task coordinator. The coordinator applies defined escalation rules. If the coordinator cannot resolve, the task escalates to human.

**Level 3 — Human coordinator decision:** A designated human coordinator reviews the escalation record and makes a decision. The decision is logged against the task record. If the decision establishes a new resolution rule that should be applied in future, it is submitted for incorporation into the agent's defined rules — through a governed development process, not at runtime.

**Level 4 — Work-product scope rejection:** If the task cannot be resolved within current agent-team scope, it is closed with `TASK_CLOSED_WITH_BLOCKER` and returned to the requestor with a clear explanation of what scope expansion or capability development is required before resubmission.

No agent is authorised to expand its own capability scope. No agent is authorised to approve its own output. No agent-team output becomes a registered work product without engineer approval.

---

## 4.12 Loop-Based Validation Methodology

Validation is structured as six progressive levels. Each level builds on evidence from the previous. Progression to the next level requires meeting defined pass criteria — not time elapsed.

**Level 1 — Single capability, controlled inputs**  
One agent, one work-product type, pre-validated input packages. Measure: task acceptance rate, output quality against defined criteria, revision count to approval. Pass criteria: ≥80% of tasks reach `TASK_HUMAN_APPROVED` within 3 revision passes.

**Level 2 — Sequential handoff, two agents**  
Drafting agent + review agent in sequence. Measure: handoff integrity (result package completeness), review accuracy, revision loop stability. Pass criteria: ≥80% of review-stage handoffs complete without `INTERFACE_CONFLICT` failure; ≥75% of drafts reach `TASK_READY_FOR_HUMAN_APPROVAL` within 3 revision passes.

**Level 3 — Full lifecycle, single work-product type**  
All five agent roles engaged on a single work-product type. Measure: end-to-end task closure rate, failure category distribution, coordinator escalation rate. Pass criteria: ≥70% of tasks reach `TASK_CLOSED_SUCCESSFULLY`; escalation rate below 20%.

**Level 4 — Multi-type coverage**  
Full lifecycle across three or more representative work-product types. Measure: type-specific pass rates, cross-type failure pattern comparison. Pass criteria: each work-product type achieves Level 3 pass criteria independently.

**Level 5 — Sustained workload**  
Sustained agent-team operation across a representative daily task volume over a 14-day period. Measure: throughput stability, failure rate trend, coordinator workload. Pass criteria: no increasing failure rate trend; throughput variation within ±30% across the 14-day period.

**Level 6 — Controlled autonomy readiness assessment**  
Structured assessment against defined go/no-go criteria. Not a pass/fail on task execution — a governance decision. The assessment asks: given the evidence from Levels 1–5, is the agent-team operating within a scope and failure rate that supports expanding the boundary of engineer oversight? The outcome is a documented recommendation, not an autonomous decision.

---

## 4.13 Workload, Capacity, and Bottleneck Analytics

Validation generates capacity data as a by-product of structured task execution. The following metrics are tracked throughout the 90-day period:

| Metric | Description | Collected at |
|--------|-------------|--------------|
| Tasks per day | Volume of task packages submitted and accepted | Daily |
| Time-in-state | Duration each task spends in each lifecycle state | Per task |
| Agent utilisation | Proportion of time each agent role is active vs. waiting | Per validation run |
| Revision count distribution | Distribution of revision passes required before human approval | Per task closed successfully |
| Failure category frequency | Count by failure category | Weekly |
| Coordinator escalation rate | Proportion of tasks requiring human coordinator intervention | Weekly |
| Infrastructure throughput | GPU utilisation, generation latency, retrieval latency | Per validation run |

At days 30, 60, and 90, a capacity review is conducted. The capacity review identifies:
- The bottleneck limiting throughput (agent capability, infrastructure, human review bandwidth, input package quality)
- Whether credits are being applied to the correct bottleneck
- Adjustments to the work programme for the next 30-day period

---

## 4.14 Credits Usage Logic

Compute credits directly address the three bottlenecks that limit validation throughput:

**GPU compute** — Sustained generation and revision cycles require continuous GPU access. Development-allocation GPU capacity does not support the sustained multi-agent, multi-task validation workload described in Levels 3–5. Credits provide dedicated GPU capacity for the 90-day validation period without interrupting live development work.

**Vector infrastructure** — The M2 knowledge retrieval layer requires a persistent, high-recall vector retrieval service. Validation of RAG-augmented generation — where drafting agents retrieve from approved precedent documents rather than generating from instructions only — requires vector infrastructure at a scale above the current development dataset. Credits fund the vector service capacity required for Level 4 and Level 5 validation runs.

**Evaluation API quota** — Framework-alignment review runs at development-tier rate limits during M1 development. Level 3–5 validation requires framework-alignment review for every draft across a sustained task volume. Credits provide the API quota required to run review at validation throughput without manual throttling.

Credits are not used for: marketing, hiring, external consulting, or non-compute operational costs.

---

## 4.15 90-Day Work Programme

### Days 1–30: Task Contract Definition and Level 1–2 Validation

**Objective:** Define all task contracts and lifecycle rules; achieve Level 1 and Level 2 validation pass criteria for at least one work-product type.

Key work items:
- Finalise task package contract schema for all five agent roles
- Finalise result package contract schema
- Define input acceptance gate rules for each agent role
- Define failure categorisation taxonomy (complete, with resolution rules for each category)
- Define Level 1 and Level 2 pass criteria (specific numeric targets)
- Run Level 1 validation: drafting agent alone, single work-product type, pre-validated inputs
- Analyse Level 1 failure log; identify and address top failure categories
- Run Level 2 validation: drafting agent + review agent in sequence
- Analyse Level 2 handoff integrity; address interface conflicts
- Conduct Day 30 capacity review: identify throughput bottleneck, adjust 31–60 plan

**Infrastructure dependency:** GPU compute for sustained Level 1–2 generation runs; evaluation API quota for Level 2 review validation.

### Days 31–60: Full Lifecycle and Multi-Type Coverage

**Objective:** Achieve Level 3 and Level 4 pass criteria; begin capacity data collection for Level 5 planning.

Key work items:
- Engage all five agent roles in full lifecycle validation (Level 3)
- Analyse Level 3 failure distribution; address top failure categories by agent role
- Expand to three or more representative work-product types (Level 4)
- Compare type-specific pass rates; identify type-specific failure patterns
- Begin M2 knowledge retrieval layer integration: validate RAG-augmented drafting agent against approved precedent document set
- Measure retrieval latency and recall quality under validation workload
- Define Level 5 pass criteria and 14-day sustained workload volume
- Conduct Day 60 capacity review: assess readiness for Level 5, adjust infrastructure allocation

**Infrastructure dependency:** GPU compute for multi-type, full-lifecycle runs; vector infrastructure for RAG-augmented drafting; evaluation API quota for multi-type review validation.

### Days 61–90: Sustained Workload and Controlled Autonomy Readiness Assessment

**Objective:** Complete Level 5 sustained workload validation; produce Level 6 controlled autonomy readiness assessment and documented go/no-go recommendation.

Key work items:
- Run Level 5: 14-day sustained workload period at defined representative daily task volume
- Monitor throughput stability, failure rate trend, coordinator workload daily
- Flag and investigate any increasing failure rate trend immediately
- Compile end-of-90-day evidence package: Level 1–5 pass/fail records, failure category analysis, capacity model, infrastructure utilisation
- Conduct Level 6 assessment: apply go/no-go criteria against evidence package
- Produce controlled autonomy readiness recommendation with supporting evidence
- Document which agent capabilities are validated for expanded scope, which require further development
- Produce 90-day outcome report (see section 4.16)
- Conduct Day 90 capacity review: document infrastructure lessons for future credit applications

**Infrastructure dependency:** GPU compute for sustained Level 5 runs; vector infrastructure stability under sustained workload; evaluation API quota for sustained review throughput.

---

## 4.16 End-of-90-Day Outcome

The output at day 90 is not an achievement of autonomous operation. It is a structured body of evidence and a documented recommendation.

**Evidence package includes:**
- Task contract and lifecycle definitions (final, version-controlled)
- Level 1–5 validation records with pass/fail status and supporting data
- Failure category analysis: frequency, resolution, outstanding gaps
- Capacity model: throughput, latency, utilisation, bottleneck identification
- Infrastructure performance record: GPU, vector, evaluation API

**Recommendation document includes:**
- Go/no-go assessment against defined Level 6 criteria
- Which agent capabilities are validated for expanded scope
- Which agent capabilities require further development before scope expansion
- Which human governance checkpoints are required at each scope boundary
- Recommended infrastructure allocation for the next validation phase
- Conditions under which the recommendation should be revisited

**What the recommendation does NOT include:**
- A claim that the system is production-ready
- A claim that autonomous operation is safe or appropriate at any scope
- A claim that any specific work-product type can be produced without engineer review
- A timeline for removing human approval from any lifecycle stage

The 90-day validation plan is a foundation for a governance-informed decision. The decision is made by qualified engineers, not by the system.

---

*All generated outputs require qualified human review against applicable standards before operational use.*  
*Apache-2.0 License · Development stage — not for production use without engineering review*
