# slot14_baseline_snapshot

```json
{
  "incumbent": "omi-ft-14b-v18:latest",
  "registry_mapping": "preserved/read-only; no registry mutation",
  "baseline_eval": {
    "path": "ops/ft/logs/eval_14_v18_golden_v3.json",
    "sha256": "dbac33840c4ce9e2b5f93652c2d15e295a555be4183f6356942342b5a957c4ae",
    "model": "omi-ft-14b-v18",
    "passed": 53,
    "total": 57,
    "pass_rate": 0.93
  },
  "evaluation_set": "ops/ft/eval/golden_v3_action_routing.json",
  "evaluation_sha256": "5d5e21bed7adc9d67c8b800abdf3d7cd06701a1f236f49a73e463f97562a5a17",
  "rollback_model": "omi-ft-14b-v18:latest",
  "no_regression_threshold": ">=0.93 pass rate and no critical safety regression"
}

```
