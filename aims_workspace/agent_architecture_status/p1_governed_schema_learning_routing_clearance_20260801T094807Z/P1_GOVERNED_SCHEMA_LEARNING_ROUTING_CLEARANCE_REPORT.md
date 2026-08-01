# P1 governed schema/learning/routing/clearance cycle — bounded repair

## Completed in this slice

- Added fail-closed autonomous change governance primitives: isolated branch/worktree, base commit, file/component lease, reviewer gate and direct-main denial.
- Added durable source version registry and closeout registry. Same logical source and hash reuses its version; changed hash creates the next version.
- Replayed all 142 current real raw records into an evidence-only source-version/closeout registry.
- Preserved the existing reviewer-independence and independent-clearance hardening.
- Training, model loading, promotion, registry mutation, slot mutation and raw deletion were not performed.

## Proof

- P1 governance/source tests: 4 passed after repairing a version-count bug, then the combined targeted suite passed 30 tests.
- Real replay: 142 records, 142 source versions, 142 closeouts, 0 admitted pairs, 18 rejects, 3 quality holds, 121 skill candidates.
- Live process inventory records existing dangerous-permission Claude/Codex processes as a governance risk; no process was stopped in this bounded slice.

## Status

This is not the final P1 verdict. Canonical schemas, LearningUnit extraction, semantic routing, versioned clearance decisions, route stores, real Redis cycles and automatic repair loop remain open.

Verdict: `PARTIAL_P1_GOVERNANCE_AND_SOURCE_VERSIONING_ONLY`
