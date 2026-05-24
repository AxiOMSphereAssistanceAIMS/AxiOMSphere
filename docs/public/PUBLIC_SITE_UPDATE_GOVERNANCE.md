# AxiOMSphere — Public Site Update Governance

**Document type:** Public-facing guardrail  
**Status:** ACTIVE  
**Date:** 2026-05-24  
**Branch:** main (public)

---

## Purpose

This document records the governance principles that govern updates to the AxiOMSphere public website and public GitHub repository. It is for contributor reference. It does not contain internal architecture detail.

---

## Public Surface Purpose

The public website (axiomsphereai.com) and the public GitHub repository exist for one purpose:

> To support applications for startup, API, GPU, and cloud credits by presenting a concise and credible explanation of what AxiOMSphere is building, what validated capability exists, what the development roadmap covers, and what compute credits would be used for.

---

## Current Approved Content

| Section | Approved to show | Not approved to show |
|---------|-----------------|----------------------|
| Current capability | M1 applied capability summary (work-product drafting, review, registration) | Internal agent names, model details, port assignments, infrastructure specs |
| Development roadmap | M1–M6 milestone table with development-stage framing | Internal implementation plans, known failures, gap analysis |
| 90-Day Validation | Compact strategic summary (founder-specified text) | Task schemas, state machines, failure taxonomies, numeric pass criteria |
| Privacy | Approved privacy statement | Source document content, internal dataset details |

---

## What May Not Appear on the Public Site or in the Public Repository

- API keys, tokens, or credentials of any kind
- Internal service ports, Docker network addresses, or routing topology
- Local model names, slot assignments, or VRAM figures
- Raw evaluation scores, certification pass/fail counts, or test run logs
- Internal agent failure logs or incident records
- Personal identifiable information
- Timing-based certification claims (24-hour, 72-hour, etc.)
- Autonomous capability claims (self-learning as current product)
- Capability claims above M1 current applied capability without development-stage framing
- Internal planning documents, task methodology, or architecture specifications

---

## Update Gate

Before committing any content to this repository (either branch), confirm:

1. No credentials or tokens in any committed file
2. No internal infrastructure detail (ports, model names, routing)
3. No capability claims above M1 without development-stage framing
4. No timing-based or autonomous capability claims
5. Content serves the one approved purpose: startup credit applications

---

## Credential Exposure Protocol

If a credential, token, or API key is discovered in a committed file:

1. Stop other work immediately
2. Report to the project owner with file name, line, and nature of the credential
3. Recommend key rotation before proceeding
4. Do not attempt to hide the exposure with a new commit (old commits remain in git history)
5. Await explicit decision on history remediation before any further git operations

---

*This document is public. It contains no internal architecture detail.*  
*Apache-2.0 License*
