# AIMS Platform Architecture

This document is the public architecture overview. It describes ownership and lifecycle boundaries without exposing private endpoints, hosts, credentials or operational identifiers.

## 1. Goals and non-goals

### Goals

- help specialists develop and review connected AIMS work products;
- preserve source identity, evidence, decisions and lineage;
- separate orchestration, audit, learning and model-lifecycle responsibilities;
- keep training, evaluation, promotion and rollback governed and reversible.

### Non-goals

- replacing accountable engineering judgement or approval;
- treating unverified model output as training data;
- claiming autonomous promotion without independent evaluation and rollback evidence;
- using a readiness threshold as permission to bypass lifecycle safety gates.

## 2. Component ownership

| Component | Public role | Boundary |
|---|---|---|
| AIMS Self-Learning V2 control plane | Coordinates lifecycle state, policies and evidence contracts | Does not make technical approval decisions by itself |
| Logi | Orchestrates governed work, captures transitions and routes evidence | Owns orchestration and handoff state |
| Auditor | Performs an independent quality/acceptance decision where independence is certified | A proposed or uncertified adapter is not an independent gate |
| Traini | Consumes eligible approved pairs and executes the governed learning lifecycle | Cannot consume raw or quarantined material |
| Redis | Queue, wake-up, lease and fencing coordination | Non-authoritative; loss must not alter durable lifecycle state |
| Authoritative lifecycle store | Durable readiness, manifest, run, lease, artifact, decision and consumption records | Single source of truth for lifecycle state |

## 3. Control plane and data plane

The control plane governs identity, policy, ownership, state transitions, leases, fencing and evidence. The data plane carries authorised source material and derived work products through explicit lifecycle states.

```text
Authorised sources
  → governed ingestion and identity
  → Logi orchestration
  → audit decision and receipt
  → approved-pair accumulation or quarantine
  → Traini readiness
  → preflight and scheduled execution
  → evaluation
  → promotion or rollback decision
```

Redis may project disposable coordination state, but it is not the source of truth for any transition.

## 4. Data lifecycle and lineage

Every material must retain a stable identity and evidence chain. A material may be held, rejected, quarantined or admitted only through a governed transition. Receipts bind decisions to source and derived hashes. Raw transcripts and failed captures are evidence, not training data, until the applicable quality, provenance and policy gates are satisfied.

The quarantine lifecycle preserves useful evidence, prevents premature deletion and supports idempotent replay. A failed route is not silently converted into an approved pair.

## 5. Model identity and revision isolation

Learning eligibility is scoped to one exact immutable model revision. Slot, model identity and revision are separate facts and must be resolved before routing or dataset admission. Pairs from different revisions are isolated and cannot be combined to satisfy a threshold.

## 6. Audit decision lifecycle

The intended sequence is:

```text
material → audit task → independent decision
         → receipt and hash → route
```

Decisions are `PASS`, `REJECT` or `HOLD` according to the applicable contract. Replay is idempotent: it may recover a missing projection, but must not create a second decision or duplicate terminal transition.

## 7. Approved-pair accumulation

Only unique, approved, admitted and previously unconsumed pairs may enter a model-revision accumulation set. Raw, unresolved, duplicate, quarantined or policy-ineligible material remains outside the training set.

## 8. Readiness at 750 pairs

For one exact immutable model revision, 750 eligible pairs create a governed `TRAINING_READINESS` signal. The signal schedules the nearest permitted training window; it does not start training immediately and does not constitute permission to promote a model.

Before the scheduled start, the lifecycle performs preflight for resources, model identity, dataset manifest, competing runs, storage, checkpoints and rollback capability. A failed preflight produces a controlled hold/retry and preserves the evidence.

With fewer than 750 eligible pairs, the normal state is `WAITING_FOR_DATA`, not `BLOCKED` or `FAIL`.

## 9. Evaluation, promotion and rollback

Training output is an artifact with identity and checksums. Evaluation must precede any promotion decision. Promotion is a separate governed transition; rollback records the decision and restores the previously accepted binding where required. A training cycle has not occurred merely because the lifecycle is armed or eligible.

## 10. Scheduler, lease and fencing

The scheduler coordinates permitted windows and serialises conflicting work through durable state plus expiring coordination projections. Lease renewal, ownership checks and fencing tokens prevent stale workers from mutating current lifecycle state. Restart and replay must recover durable state without duplicating business transitions.

## 11. Quarantine and retention

Quarantine is a controlled lifecycle state, not deletion. Source and derived artifacts remain retained according to policy, with manifests and hashes where the transition is supported. Material stays active while an evidence or training route is open; a proposal failure alone is not permission to move the source.

## 12. Observability

Operational observation should expose state, ownership, retry/hold reason, evidence references and safe counters. Public materials report stable semantics rather than private addresses, credentials, raw payloads or rapidly changing internal counters.

## 12A. Closed pipeline branches

AIMS treats pipelines as governed, traceable state machines rather than independent
automation snippets. Every non-terminal branch has an owner, next action,
heartbeat, deadline, checkpoint, repair/recovery route, replay identity and
reconciliation rule. A pause is safe only when automatic monitoring and resume are
preserved. New mechanisms follow the repository policy
[`AIMS_AUTONOMOUS_PIPELINE_BRANCH_CLOSURE_AND_REUSE_POLICY_RU.md`](architecture/AIMS_AUTONOMOUS_PIPELINE_BRANCH_CLOSURE_AND_REUSE_POLICY_RU.md):
`REUSE → VERIFY → MODERNIZE → CREATE`.

This public overview intentionally omits internal paths, credentials, account
identities and operational topology.

## 13. Failure modes

Expected failures include unavailable models or auditors, interrupted workers, expired leases, duplicate delivery, incomplete evidence, invalid provenance and failed preflight. The safe response is hold, retry, recovery or quarantine with traceable evidence. Silent substitution, fabricated receipts and unreviewed promotion are outside the architecture contract.

## 14. Repair governance and current certification boundary

The document-development foundation is Phase 22 certified. Evidence-bound repair
contracts, runtime integration, the correlated governance trace, Logi policy-gap
capture and controlled stalled-repair restart are certified. The restart
capability was verified through a disposable non-production fault-injection
canary using the existing queue and same-lineage restart path, ending in
`COMPLETED_VERIFIED`.

The permanent runtime route is certified independently of publication. Runtime
health, loaded implementation hashes, rollback, cleanup and recovery checks
passed; publication is a separate documentation lifecycle and does not control
repair authorization or process continuity.

Repair still requires an exact proposal, independent Auditor attestation,
current-policy authorization, a fresh permit and targeted verification. Logi can
detect and prepare a governed policy-gap proposal, but cannot change Policy.
Policy activation does not restart historical repairs automatically.

The normal pre-threshold learning state is `WAITING_FOR_DATA`; training,
evaluation and promotion remain governed downstream lifecycle events and have not
occurred.
