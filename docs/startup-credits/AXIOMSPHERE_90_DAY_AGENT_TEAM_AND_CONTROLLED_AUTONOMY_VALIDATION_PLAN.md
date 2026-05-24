# AxiOMSphere 90-Day Agent-Team and Controlled Autonomy Validation Plan

**Document type:** External startup-credit development plan  
**Status:** ACTIVE — supersedes `AXIOMSPHERE_90_DAY_VALIDATION_PLAN.md`  
**Prepared:** 2026-05-24  
**Branch:** main (public)  
**Classification:** Public — startup-credit application material

---

## Purpose

This document describes the structured validation work that AxiOMSphere will conduct over a 90-day period, contingent on startup compute credit approval. The validation work targets the transition from a single-operator development workflow to a coordinated agent-team model, in which multiple specialist agents share a task registry, accept defined task packages, execute within their capability scope, and return structured outputs — all under qualified human governance at every decision boundary.

The purpose of this validation is to produce systematic, documented, repeatable evidence that a coordinated agent team can be trusted with progressively scoped capability in an industrial document workflow, and to reach a governed go/no-go decision on controlled autonomy for a bounded class of work-product tasks.

---

## Starting Point

AxiOMSphere M1 is validated and operating in its development environment:

- Engineer submits a plain-language work-product request
- System generates a structured AIMS work-product draft aligned to ISO 55001 requirements and ISO 55002 guidance
- Draft is reviewed for framework alignment; revision guidance is generated
- Engineer reviews and approves each output before registry entry
- Accepted outputs are registered with generation metadata

What is not yet validated: coordinated multi-agent execution on structured task packages, consistent agent-team behaviour across representative work-product types, and evidence-based go/no-go criteria for expanding agent-team scope.

---

## Why Credits Are Needed

Compute credits directly address three bottlenecks limiting validation throughput:

**GPU compute** — Sustained multi-agent generation and revision cycles require dedicated GPU capacity beyond what development-allocation supports without interrupting live development work.

**Vector infrastructure** — The M2 knowledge retrieval layer requires a persistent, high-recall vector retrieval service at a scale above the current development dataset.

**Evaluation API quota** — Framework-alignment review at validation throughput requires API quota above development-tier rate limits.

Credits are not used for: marketing, hiring, external consulting, or non-compute operational costs.

---

## Three-Phase Work Programme

### Phase 1 — Days 1–30: Task Contract Definition and Initial Validation

Define all task contracts and lifecycle rules. Validate single-agent and sequential two-agent execution for at least one representative work-product type. Conduct Day 30 capacity review to identify throughput bottleneck.

**Infrastructure dependency:** GPU compute; evaluation API quota.

### Phase 2 — Days 31–60: Full Lifecycle and Multi-Type Coverage

Engage all agent roles in full lifecycle validation. Expand coverage to three or more representative work-product types. Begin M2 knowledge retrieval layer integration. Conduct Day 60 capacity review.

**Infrastructure dependency:** GPU compute; vector infrastructure for RAG-augmented generation; evaluation API quota.

### Phase 3 — Days 61–90: Sustained Workload and Controlled Autonomy Assessment

Run a 14-day sustained workload validation period. Compile the end-of-90-day evidence package. Conduct the controlled autonomy readiness assessment and produce a documented go/no-go recommendation with supporting evidence.

**Infrastructure dependency:** GPU compute; vector infrastructure under sustained load; evaluation API quota.

---

## What the 90-Day Output Is

The output at day 90 is a structured evidence package and a documented governance recommendation — not a claim of autonomous operation.

The evidence package covers task contract definitions, validation pass/fail records, failure category analysis, capacity model, and infrastructure performance. The recommendation documents which agent capabilities are validated for expanded scope, which require further development, and what human governance checkpoints are required at each scope boundary.

The 90-day validation plan is a foundation for a governance-informed decision made by qualified engineers.

---

## Governance Principles

- No agent-team output becomes a registered work product without qualified engineer review and approval
- No agent is authorised to approve its own output or expand its own capability scope
- Validation levels are progression-gated on evidence, not time elapsed
- Learning is not automatic — no agent updates its behaviour without a human development decision

---

*All generated outputs require qualified human review against applicable standards before operational use.*  
*Apache-2.0 License · Development stage — not for production use without engineering review*
