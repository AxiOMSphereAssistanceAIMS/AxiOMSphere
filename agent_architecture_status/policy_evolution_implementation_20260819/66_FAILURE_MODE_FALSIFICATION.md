# 66 — Failure-Mode and Falsification Review

| Failure mode | Detection/prevention | Recovery/evidence | Result |
|---|---|---|---|
| crash during permit→queue write | lock + atomic replace; permit remains durable | retry same idempotency key; queue evidence | PASS by design/test |
| crash after queue replace | durable replaced file + CAS state | replay/reconcile same lineage | PASS |
| duplicate callback/restart | idempotency key under lock | `RECONCILED_IDEMPOTENT` | PASS |
| concurrent revalidation/restart | current policy/hash validation + queue CAS | one winner, loser reconciles | PASS |
| policy/attestation/source drift | exact hash/revision/freshness checks | re-audit/revalidation | PASS |
| owner approval replay | nonce/hash/expiry/stage validation | reject and request fresh approval | PASS |
| queue split brain | one queue authority; no second store | atomic file transaction | PASS |
| Logi restart | durable correlation root and capture identity | replay-safe capture | PASS |
| rollback or verification failure | rollback hash required; completion requires verification | remain non-terminal with next action | PASS |
| orphan canary artifact | disposable run root recreated; cleanup receipt | quarantine/cleanup review | PASS |
| legacy caller bypass | legacy backend retired fail-closed; projections no authority | rework/reaudit | PASS |
| 10×/100× backlog/evidence | bounded queue transaction and idempotent keys; scale test remains operational follow-up | retention/compaction policy | designed, benchmark scheduled |

The remaining scale benchmark is an operational measurement, not an authority gap; no public release claim depends on unmeasured throughput.
