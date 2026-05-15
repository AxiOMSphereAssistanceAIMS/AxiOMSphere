# AIMS — Code Fix (Bug · Traceback · Runtime Error)

Fix target: **$ARGUMENTS**

---

## MANDATORY: follow phases in order — never skip Phase 0

---

## Phase 0 — Context load

### 0a. Load learned rules and past lessons

```bash
cd /home/axi_omi_sphere/aims-workspace
cat aims_workspace/repairman_memory/rules_learned.md 2>/dev/null || echo "(no rules yet)"
python3 ops/agents/repair_agent/lessons_manager.py search "$ARGUMENTS" 2>/dev/null | head -30
```

### 0b. Classify the error domain

| Domain | Keywords | Key files to read |
|--------|----------|-------------------|
| `import_error` | ModuleNotFoundError, ImportError | requirements.txt, pyproject.toml |
| `agent_wiring` | handoff, 8007, 8010–8016, dispatch | ops/agents/, ops/argus/ |
| `gateway_proxy` | 8082, 500, API Error, proxy | ops/gateway/anthropic_proxy.py |
| `db_registry` | sqlite3, aims_registry.db, locked | data/aims_registry.db schema |
| `model_routing` | VRAM, ollama, model loading, resolve_slot | ops/router/, core/router/ |
| `ft_pipeline` | train, QLoRA, dataset, eval, GGUF | ops/ft/scripts/, ops/ft/logs/ |
| `bot_handler` | Telegram, handler, axi_bot, omi_bot | ops/axi_bot.py, ops/agents/ |

### 0c. Locate the failing code

```bash
# If traceback given — find file:line
grep -rn "<symbol from $ARGUMENTS>" ops/ core/ --include="*.py" | head -20

# Recent error logs
ls -lt aims_workspace/pids/ aims_workspace/batch_failed/ 2>/dev/null | head -10
journalctl -u aims-* --since "1 hour ago" 2>/dev/null | tail -30
docker logs aims-axi-bot --tail=50 2>/dev/null
```

---

## Phase 1 — Diagnosis

Answer before touching any file:
1. What exact line fails and why?
2. What is expected vs actual behaviour?
3. Is there a past lesson for this pattern?
4. What is the minimum change to fix it?

---

## Phase 2 — Fix

Apply the minimal fix. Rules:
- No hallucinated imports — verify all symbols exist before adding
- No deletion of working code — only change what breaks
- No hardcoded model names — use `resolve_slot("N")` or env var
- No `.env` write — read BOM-safe: `sed 's/^\xEF\xBB\xBF//'`

---

## Phase 3 — Verify

```bash
# Run affected tests
python -m pytest ops/tests/ -v -k "<module_name>" --tb=short 2>&1 | tail -30

# If bot handler — check import at minimum
python3 -c "import sys; sys.path.insert(0,'ops'); import <module>" 2>&1
```

---

## Phase 4 — Lesson capture

```bash
# Save lesson if fix was non-obvious
python3 ops/agents/repair_agent/lessons_manager.py add \
  --problem "$ARGUMENTS" \
  --root_cause "<one sentence>" \
  --fix "<what was changed>" \
  --files_changed "<path1,path2>" \
  --test_result "pass" 2>/dev/null || echo "(lessons_manager not available — log manually)"
```

---

## Phase 5 — Output contract

```json
{
  "problem": "$ARGUMENTS",
  "root_cause": "<one clear paragraph>",
  "files_changed": ["<path>"],
  "patch_summary": "<what was changed and why>",
  "tests_run": ["<command>"],
  "test_result": "pass | fail | not_run",
  "risk_level": "low | medium | high",
  "rollback_notes": "<how to revert>",
  "lesson_saved": true,
  "slot_used": "32"
}
```
