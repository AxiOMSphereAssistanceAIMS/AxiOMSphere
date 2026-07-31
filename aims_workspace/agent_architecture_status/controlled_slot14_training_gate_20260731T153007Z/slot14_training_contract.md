# slot14_training_contract

```json
{
  "status": "PROPOSAL_ONLY_NOT_AUTHORIZED",
  "base_model": "omi-ft-14b-v18:latest",
  "dataset_manifest_sha256": "28347ae3cb1346755ed23e1327a07e8a9059e048e59ebfe13f1c8a5e06a46f24",
  "method": "QLoRA (proposal)",
  "max_steps": 100,
  "epochs": 1,
  "batch_size": 1,
  "sequence_length": 2048,
  "checkpoint_interval": 25,
  "timeout_seconds": 1800,
  "gpu_memory_guard": "abort if free memory below configured floor or OOM",
  "abort_conditions": [
    "OOM",
    "dataset hash mismatch",
    "cross-slot material",
    "quality/provenance failure"
  ],
  "promotion_allowed": false,
  "registry_change_allowed": false,
  "slot_update_allowed": false
}

```
