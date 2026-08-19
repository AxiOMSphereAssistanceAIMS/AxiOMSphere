# 63 — Canonical Authority and State Model

The semantic lifecycle is implemented in `ops/policy_evolution/state_model.py`. It is a transition relation, not a collection of independent labels. Every state has one deterministic `next_action_id`; terminal states have `NONE`.

The governed path is:

`DETECTED → DIAGNOSED → PROPOSAL_READY → AUDIT_REQUIRED → AUDITED → POLICY_EVALUATION → AUTHORIZED → QUEUED → EXECUTING → VERIFYING → COMPLETED_VERIFIED`.

The stale/restart path is:

`STALLED → REVALIDATION_REQUIRED → REVALIDATING → READY_FOR_NEW_PERMIT → PERMIT_ISSUED → RESTART_QUEUED → RESTARTING → EXECUTING`.

Queue storage remains the single execution authority and only performs existing-lineage CAS. Governance records remain in `GovernedExecutionStore`; no synchronizer or parallel repair store was introduced.
