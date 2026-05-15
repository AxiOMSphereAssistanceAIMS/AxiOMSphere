# AIMS — Fine-Tuning Pipeline (Status · Restart · Config · Eval)

Operation: **$ARGUMENTS**

---

## Phase 0 — Parse request

From `$ARGUMENTS` determine:
- **op**: `status` | `restart` | `eval` | `config` | `retarget` | `logs` | `dataset`
- **run**: specific run name (e.g. `v15`, `qwen3_32b_v1`) or "latest"
- **model**: target model (for retarget)

---

## Phase 1 — Pipeline status

```bash
cd /home/axi_omi_sphere/aims-workspace

# Active training processes
ps aux | grep -E "train_qlora|ft_pipeline|run_v" | grep -v grep | head -10

# Recent run logs (newest first)
ls -lt ops/ft/logs/ | head -15

# Last log tail
latest_log=$(ls -t ops/ft/logs/*.log 2>/dev/null | head -1)
echo "=== Latest log: $latest_log ==="
tail -40 "$latest_log" 2>/dev/null

# Eval results
ls -lt ops/ft/logs/eval_*.json 2>/dev/null | head -5
cat $(ls -t ops/ft/logs/eval_*.json 2>/dev/null | head -1) 2>/dev/null | python3 -m json.tool | head -30
```

---

## Phase 2 — Config inspection

```bash
# Active configs
ls -la ops/ft/configs/

# Show target config
cat "ops/ft/configs/train_config_$ARGUMENTS.json" 2>/dev/null || \
  cat $(ls -t ops/ft/configs/train_config_*.json | head -1) 2>/dev/null | python3 -m json.tool

# Dataset versions
ls -la ops/ft/data/ | head -20

# Output adapters
ls -la ops/ft/output/ 2>/dev/null | head -20

# Ollama models (deployed adapters)
curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "
import sys, json
[print(m['name']) for m in json.load(sys.stdin).get('models',[])]
" | grep "omi\|aims\|qwen" | head -15
```

---

## Phase 3 — Restart pipeline

```bash
# Full v15 pipeline (train → merge → GGUF → Ollama → eval)
# bash ops/ft/scripts/run_v15.sh

# Skip training, run eval only
# bash ops/ft/scripts/run_v15.sh --skip-train

# Standalone eval
# ops/ft/.venv/bin/python ops/ft/scripts/eval_actions.py \
#   --model omi-ft-14b-v15 \
#   --suite ops/ft/eval/golden_v2.json \
#   --out ops/ft/logs/eval_result_$(date +%Y%m%d_%H%M).json
```

**Before restart:**
- Verify VRAM headroom: `nvidia-smi`
- Slot 120 unloaded (training needs ~80-90 GB)
- No concurrent heavy training

---

## Phase 4 — Retarget config (change model_name_or_path)

**Retarget config from `$ARGUMENTS` to new model.**

Changes required in config JSON:
```json
{
  "model_name_or_path": "<new HuggingFace path>",
  "output_dir": "ops/ft/output/adapter_<new_name>",
  "run_name": "<new_run_name>"
}
```

For qwen3-coder:30b retarget:
```json
{
  "model_name_or_path": "Qwen/Qwen3-Coder-30B",
  "output_dir": "ops/ft/output/adapter_qwen3_coder_30b_v1",
  "run_name": "qwen3_coder_30b_v1",
  "enable_thinking": false,
  "gradient_checkpointing": true
}
```

---

## Phase 5 — Dataset status

```bash
# Training pairs accumulated
wc -l aims_workspace/axi_ft_log/gold_pairs.jsonl 2>/dev/null && echo "gold pairs"
wc -l aims_workspace/axi_ft_log/dpo_pairs.jsonl 2>/dev/null && echo "DPO pairs"

# Dataset files
wc -l ops/ft/data/*.jsonl 2>/dev/null | sort -rn | head -10

# Eval suite
cat ops/ft/eval/coding_golden_v1.json 2>/dev/null | python3 -c "
import sys, json; d = json.load(sys.stdin)
cases = d if isinstance(d, list) else d.get('cases', [])
print(f'Eval suite: {len(cases)} cases')
" 2>/dev/null
```

---

## Phase 6 — Output contract

```json
{
  "operation": "$ARGUMENTS",
  "training_active": false,
  "latest_run": "<run_name>",
  "latest_eval_score": null,
  "eval_target": 1.0,
  "config_path": "<path>",
  "dataset_gold_pairs": 0,
  "dataset_dpo_pairs": 0,
  "vram_required_gb": 80,
  "vram_available_gb": 0,
  "ready_to_train": false,
  "slot_used": "32"
}
```
