# AIMS — Model Slot Management (Resolve · Update · Audit · Routing)

Operation: **$ARGUMENTS**

---

## Phase 0 — Parse operation

From `$ARGUMENTS` determine:
- **op**: `resolve` | `status` | `audit` | `swap` | `update-registry` | `list`
- **slot**: 8 | 14 | 32 | 120 (or "all")
- **model**: target model name (for swap/update-registry)

---

## Phase 1 — Current slot state

```bash
cd /home/axi_omi_sphere/aims-workspace

# Registry bindings
cat ops/models/model_registry.yaml 2>/dev/null || \
  cat ops/config/model_registry.yaml 2>/dev/null | head -60

# Models currently loaded in Ollama
curl -s http://localhost:11434/api/ps 2>/dev/null | python3 -m json.tool

# All available Ollama models
curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    size_gb = m.get('size', 0) / 1e9
    print(f\"{m['name']:50s}  {size_gb:.1f} GB\")
"

# VRAM budget
nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv,noheader,nounits 2>/dev/null
```

---

## Phase 2 — Slot resolve

```bash
# Use the AIMS resolve function (never hardcode model names)
python3 - <<'EOF'
import sys
sys.path.insert(0, 'ops')
try:
    from models.model_registry import resolve_slot
    for slot in [8, 14, 32, 120]:
        try:
            model = resolve_slot(str(slot))
            print(f"Slot {slot}: {model}")
        except Exception as e:
            print(f"Slot {slot}: ERROR — {e}")
except ImportError as e:
    print(f"Cannot import resolve_slot: {e}")
    print("Check: ops/models/model_registry.py or core/router/model_router.py")
EOF
```

---

## Phase 3 — Routing audit

```bash
# Hardcoded model names in code (violation of slot rule)
grep -rn "qwen3:32b\|nemotron-3-super\|omi-ft-14b\|qwen2.5-aims" \
  ops/ core/ --include="*.py" | grep -v "model_registry\|resolve_slot\|test_\|#" | head -20

# Routing logic paths
find ops/router/ core/router/ -name "*.py" 2>/dev/null | xargs grep -ln "resolve_slot\|model_name" | head -10

# Candidate registry (slot 32 candidates)
cat ops/models/model_candidate_registry.yaml 2>/dev/null | head -40
```

---

## Phase 4 — Swap / update-registry (requires explicit confirmation)

**STOP:** Model registry changes affect all running agents. Confirm before proceeding:
- Is the new model downloaded and smoke-tested?
- Is the old model still available as rollback?
- Is the cleanup manifest updated?

```bash
# Update registry binding (edit model_registry.yaml)
# Do NOT use sed — use Edit tool with explicit old/new values

# Verify after change
python3 - <<'EOF'
import sys; sys.path.insert(0, 'ops')
from models.model_registry import resolve_slot
print("Slot 32:", resolve_slot("32"))
EOF
```

---

## Phase 5 — Candidate lifecycle status

```bash
# Check candidate intake status
ls -lt aims_workspace/audit/model_candidate_intake_*.json 2>/dev/null | head -5
cat aims_workspace/audit/model_candidate_intake_$(ls -t aims_workspace/audit/model_candidate_intake_*.json 2>/dev/null | head -1 | xargs basename) 2>/dev/null

# Benchmark status
ls -lt aims_workspace/audit/model_candidate_benchmark_*.json 2>/dev/null | head -5
```

---

## Phase 6 — Output contract

```json
{
  "operation": "$ARGUMENTS",
  "slot_bindings": {
    "8": "<model>",
    "14": "<model>",
    "32": "<model>",
    "120": "<model>"
  },
  "vram_loaded_gb": 0.0,
  "vram_free_gb": 0.0,
  "hardcoded_violations": 0,
  "registry_changed": false,
  "rollback_available": true,
  "slot_used": "32"
}
```
