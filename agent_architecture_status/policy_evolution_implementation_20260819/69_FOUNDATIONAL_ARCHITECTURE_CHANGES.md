# 69 — Foundational Architecture Changes

1. Reused the existing repair queue as the sole execution authority and modernized its transaction boundary with inter-process locking, atomic replace and fsync.
2. Created the missing canonical semantic state model and deterministic next-action map.
3. Made attestation, permit and owner approval freshness explicit and fail closed.
4. Retired the legacy Repairman execution fallback instead of keeping a compatibility bypass.
5. Kept Logi policy-gap capture as a permanent, idempotent, second-pass-gated boundary.
6. Formalized the fault-injection harness as reusable assurance over the same runtime primitives.

No production source document, production database, policy activation, training path or production repair queue was mutated.
