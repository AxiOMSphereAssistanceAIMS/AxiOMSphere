# 63 — Canonical Authority and State Model

`state_model.py` owns semantic transitions and deterministic next actions. `repair_queue.py` owns physical execution-lineage state and CAS. `GovernedExecutionStore` owns governance events. Poli owns authorization; Logi owns causal intake and gap classification; Repairman owns bounded execution only after permit validation.

The positive and stalled/restart paths are one lifecycle. Terminal states are `COMPLETED_VERIFIED` and `OBSOLETE_CASE`; every non-terminal state has a deterministic action. Expired permits, changed policy/source, superseded attestations, stale approvals, replay and illegal transitions fail closed.
