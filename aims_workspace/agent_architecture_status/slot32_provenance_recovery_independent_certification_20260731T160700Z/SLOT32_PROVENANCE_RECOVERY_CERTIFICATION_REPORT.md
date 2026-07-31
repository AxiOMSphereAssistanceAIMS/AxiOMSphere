# Slot32 Provenance Recovery and Independent Certification

Generated: 20260731T160700Z

The physical dataset `/home/axi_omi_sphere/aims-workspace/ops/ft/data/repairman_slot32_v1/train_repairman_slot32_v1.jsonl` contains 3 rows, while its generation summary declares 1,095 approved pairs from 5,316 source rows. This inconsistency is an independent audit blocker. The source adjudication is `FAIL_QUALITY_GATE`; the transformation gate is `UNPROVEN_SELF_ASSERTED_TRANSFORMATION_FLAG`; and each inspected row has `approved_for_training=false`.

No row was independently certified. Certified count is 0/750, so fresh terminal source acquisition is required. The incumbent `Qwen/Qwen3-Coder-Next-FP8` and `model=slot32` launcher contract were preserved. No training task, model load, evaluation, candidate build, promotion, registry change, or slot mutation occurred.

Verdict: `HOLD_SLOT32_PROVENANCE_GAP`.
