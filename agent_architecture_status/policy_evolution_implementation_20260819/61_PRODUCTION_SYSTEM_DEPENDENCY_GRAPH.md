# 61 — Production System Dependency Graph

The production lifecycle uses one connected authority chain: `Failure/Logi causal event → repair case → proposal → AuditorAttestation → Poli policy decision → ExecutionPermit → existing repair_queue CAS → Repairman governed execution → verification → completion evidence`.

Stalled cases use the same lineage through `RevalidationDisposition → fresh permit → existing-lineage RepairRestartRecord → queue reconciliation`. Logi policy-gap capture is an event-driven classification boundary; it can create a candidate trigger only after complete evidence and second-pass agreement. It never changes policy or queue state.

Canonical owners are: Logi v2 causal store for causal events; GovernedExecutionStore for governance events; `policy_evolution.contracts` for hash-bound envelopes; `state_model` for semantic state; Poli for authorization; existing `repair_queue` for execution lineage; Repairman for bounded execution after permit validation. Compatibility projections are read-only and no publication component participates in runtime authorization.
