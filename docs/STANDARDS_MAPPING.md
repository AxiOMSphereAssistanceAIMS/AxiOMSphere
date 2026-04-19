# ISO/IEC Standards Mapping — AIMS Agent Capabilities

This document maps each supported standard to the specific agent capabilities and document sections it governs.

## ISO 45001:2018 — Occupational Health & Safety

| Clause | Requirement | AIMS Implementation |
|--------|-------------|---------------------|
| §6.1.2 | Hazard identification and risk assessment | JSA hazard table with risk matrix |
| §8.1.3 | Management of change | MOC procedure generation |
| §8.2 | Emergency preparedness | Emergency response procedure generation |
| §9.1 | Monitoring, measurement, analysis | KPI section in safety documents |
| §10.2 | Incident investigation | Incident report template |

## ISO 21502:2020 — Project Management

| Clause | Requirement | AIMS Implementation |
|--------|-------------|---------------------|
| §4 | Project context | Scope and stakeholder sections |
| §6.5 | Work breakdown structure | WBS generation from project scope |
| §7.3 | Risk management | Risk register template |
| §9 | Transition and benefits | Project closure checklist |

## ISO 21500:2021 — Portfolio/Programme Management

| Clause | Requirement | AIMS Implementation |
|--------|-------------|---------------------|
| §4.3 | Governance | Project charter governance section |
| §4.4 | Stakeholders | Stakeholder matrix generation |
| §4.5 | Value creation | Business case structure |

## IEC/IEEE 82079-1:2019 — Technical Documentation

| Clause | Requirement | AIMS Implementation |
|--------|-------------|---------------------|
| §5.3 | Target audience analysis | User documentation profiling |
| §6.2 | Safety information | Warning/caution structure |
| §7.4 | Instructions for use | Step-by-step procedure format |
| §8 | Document quality | Gemini scoring criteria |

## ISO 9001:2015 §7.5 — Documented Information Control

| Requirement | AIMS Implementation |
|-------------|---------------------|
| Document identification | Auto-generated doc ID, revision, date |
| Version control | Revision field in document header |
| Approval process | Score gate (≥0.8) before delivery |
| Access control | Telegram chat allowlist |

## API RP 505 — Fire Protection for Refineries

| Section | Requirement | AIMS Implementation |
|---------|-------------|---------------------|
| §4 | Fire hazard analysis | FHA section in ERP documents |
| §5 | Fire control systems | Detection/suppression inventory |
| §6 | Emergency response | ERP procedure with API RP 505 references |

## Gemini Scoring Rubric

The quality gate prompt explicitly scores against all 6 standards:

```
Criteria: ISO 45001, API RP 505, ISO 21502:2020, ISO 21500:2021,
          IEC/IEEE 82079-1:2019, ISO 9001 §7.5, HSE best practices.
Score 0.0 = completely missing required content
Score 1.0 = fully compliant with all applicable clauses
```

Threshold for delivery: **score ≥ 0.80**
Threshold for training gold pair: **score ≥ 0.80**
Auto-retry below: **score < 0.60**
