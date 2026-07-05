# AIMS Pipeline Inventory — Logi Chief Engineer Orchestrator
Generated: 2026-07-06

## 1. Existing AIMS Pipelines (from ops/logi/)

| Module | Capability | Reuse Decision |
|--------|-----------|----------------|
| `capability_assessor.py` | Gap analysis when service unavailable | EXTEND for capability_gap skill |
| `strategic_planning.py` | Multi-day horizon plans, goal ledger | EXTEND for plan_task/decompose_task |
| `process_goals.py` | Structured goal model, PLANNED→PASS/FAIL | EXTEND for sprint pipeline |
| `artifact_fallback_writer.py` | Structured artifact writer to evidence dir | EXTEND for artifact store |
| `ai_intent_router.py` | Intent classification (command/question/execute) | EXTEND for mode router |
| `syntax_interpreter.py` + `syntax_policy.py` | Intent policy evaluation | EXTEND |
| `skill_registry.py` (ops/agents) | Named skill registry | EXTEND for skill system |
| `self_test_catalog.py` | Self-test capability catalog | EXTEND for QA skill |
| `conversational_orchestrator.py` | Main Logi run() dispatcher | EXTEND (injection point) |
| `logi_confirmation_flow.py` | Protected action confirmation | EXTEND (new action types) |
| `logi_assistant_gateway.py` | Gateway dispatcher | EXTEND for mode routing |
| `verified_learning_event_recorder.py` | Learning event JSONL writer | EXTEND for learning_registration |
| `model_self_check.py` | Self-check for fake output / policy violations | EXTEND for self_check skill |
| `codex_auditor_adapter.py` | Auditor chain (Codex/Bedrock) | EXTEND for auditor_request skill |
| `claude_review_queue.py` | Claude Code review queue | EXTEND for review skill |
| `agent_training_material_index.py` | Training material index | EXTEND for learn skill |
| `process_ledger.py` | Process state ledger | EXTEND for sprint state |
| `plans.py` | Plan management | EXTEND for plan_task |

## 2. Existing Protected Actions (confirmation flow)

Already implemented in `ops/agents/logi_confirmation_flow.py`:
- `healthcheck_service` ✅
- `read_logs_allowlisted` ✅
- `diagnose_service_allowlisted` ✅

## 3. Existing Auditor Route

`ops/agents/codex_auditor_adapter.py` + launchers in `ops/scripts/`:
- `codex_auditor_primary.sh`
- `codex_auditor_secondary.sh`
- `claude_bedrock_auditor.sh`

Status: AVAILABLE (Claude Bedrock AVAILABLE, Codex NOT_CONFIGURED)

## 4. Existing Scheduler/Redis Integration

- `ops/scheduler/` — Redis task scheduler, heartbeat, VRAM checker
- `axiomsphere-redis-scheduler` container — Up
- `axiomsphere-task-registry` — Up (port 8765)
- `axiomsphere-queue-api` — Up (port 8766)
- `axiomsphere-aims-scheduler-1` — Up

## 5. Existing Learning/Training Pipeline

- `ops/agents/verified_learning_event_recorder.py` — JSONL event writer
- `ops/agents/model_self_check.py` — self-check for fake output
- `ops/logi/traini_*.py` — training lifecycle modules
- `ops/agents/self_learning/` — full skill lifecycle (candidate→certified)
- `axiomsphere-traini-worker` — Up

## 6. Existing Evidence Ledger Convention

- `aims_workspace/agent_architecture_status/` — evidence packages
- `aims_workspace/logi_artifacts/` — Logi skill artifacts (exists)
- `aims_workspace/logi_confirmations/` — confirmation ledger (exists)
- `aims_workspace/self_learning/inbox/` — learning JSONL (used by verified_learning_event_recorder)

## 7. Existing Docker Containers Relevant to Logi

| Container | Purpose | Status |
|-----------|---------|--------|
| axiomsphere-logi-bot | Logi Telegram bot | Up |
| axiomsphere-logi-cc-bridge | Claude Code host bridge | Up |
| axiomsphere-logi-cc-slot32-proxy | Slot32 proxy | Up |
| axiomsphere-argus-bot | Infrastructure monitoring | Up |
| axiomsphere-repairman-api | Repair executor (port 8010) | Up |
| axiomsphere-architect-agent | Architecture gate (8011) | Up |
| axiomsphere-security-agent | Security gate (8012) | Up |
| axiomsphere-qa-agent | QA gate (8013) | Up |
| axiomsphere-release-agent | Release gate (8014) | Up |
| axiomsphere-docs-agent | Docs advisory (8015) | Up |
| axiomsphere-watchdog-agent | Health aggregator (8016) | Up |
| axiomsphere-mainy-repair-agent | Repair executor (8005) | Up |

## 8. Existing Agents and Contracts

Already running self-healing agents:
- RepairmanAPI → repair/diagnose (8010)
- Architect → architecture review (8011)
- Security → security gate (8012)
- QA → test/coverage (8013)
- Release → release gate (8014)
- Docs → documentation advisory (8015)
- Watchdog → health (8016)
- Mainy → repair executor (8005)
- Argus → infrastructure monitoring

## 9. gstack Functions Already Covered

| gstack Role | AIMS Equivalent | Status |
|-------------|----------------|--------|
| Security officer | security-agent (8012) | RUNNING |
| QA lead | qa-agent (8013) | RUNNING |
| Release engineer | release-agent (8014) | RUNNING |
| Architecture review | architect-agent (8011) | RUNNING |
| Repair | repairman-api (8010) + mainy | RUNNING |
| Docs | docs-agent (8015) | RUNNING |
| Health | watchdog-agent (8016) | RUNNING |
| Learning | verified_learning_event_recorder | IMPLEMENTED |
| Auditor | codex_auditor_adapter | IMPLEMENTED |

## 10. Functions Missing (need extension or new module)

| Missing Function | Action |
|-----------------|--------|
| Capability mode router (classify intent → skill) | CREATE NEW (no analog covers all 19 modes) |
| Skill system (skill registry + output schema) | EXTEND ops/agents/skill_registry.py |
| Artifact store (per-skill artifact writer) | EXTEND ops/logi/artifact_fallback_writer.py |
| Sprint pipeline (goal→phase→next skill) | EXTEND ops/logi/strategic_planning.py |
| Task queue pending artifacts | CREATE NEW (no pending dir exists) |
| Auditor request artifact writer | CREATE NEW (no pending dir exists) |
| Skill request governance | CREATE NEW (no skill_requests dir) |
| Learning registration via confirmation | EXTEND verified_learning_event_recorder |

## 11. Reuse Plan

| Module | Decision | Justification |
|--------|---------|---------------|
| `conversational_orchestrator.run()` | EXTEND | Injection point for mode routing |
| `logi_assistant_gateway.process_gateway_message()` | EXTEND | Add mode dispatch |
| `logi_confirmation_flow.py` | EXTEND | New action types: auditor_request, skill_request, learning_registration |
| `capability_assessor.py` | EXTEND | capability_gap skill reuses gap report structure |
| `verified_learning_event_recorder.py` | EXTEND | learning_registration writes here |
| `codex_auditor_adapter.py` | EXTEND | auditor_request routes here |
| `skill_registry.py` | EXTEND | Skill system adds chief-engineer skills |
| `artifact_fallback_writer.py` | EXTEND (pattern) | Artifact store follows same convention |
| `strategic_planning.py` | EXTEND (pattern) | Sprint pipeline follows same ledger |
| Self-healing agents (8010-8016) | REUSE via HTTP | review/security/qa/release skills delegate here |

## 12. New Modules Required (with justification)

| Module | Why new | Risk |
|--------|---------|------|
| `logi_capability_mode_router.py` | No single module routes all 19 gstack modes; ai_intent_router only handles basic 10 intents | LOW |
| `logi_skill_system.py` | skill_registry.py is for agent skills, not chief-engineer process skills | LOW |
| `logi_artifact_store.py` | artifact_fallback_writer is for overflow; skill artifacts need per-skill paths | LOW |
| `logi_sprint_pipeline.py` | strategic_planning.py is for weeks-horizon; sprint is per-conversation | LOW |
| `logi_task_queue.py` | No pending task dir exists; extends scheduler safely | LOW |
| `logi_auditor_request.py` | No pending auditor dir exists | LOW |
| `logi_skill_request.py` | No skill_requests dir exists | LOW |
| `logi_learning_recorder.py` | Thin wrapper over verified_learning_event_recorder with confirmation | LOW |

## 13. Duplication Risk: LOW

All new modules are thin wrappers/extensions. No parallel agent containers. All routing
goes through existing conversational_orchestrator.run() injection points. All storage
uses existing evidence ledger convention.

## 14. Tests to Run After Each Layer

```bash
python -m pytest ops/agents/tests/ -q --tb=no
bash ops/scripts/verify_local_executor_extended.sh
```

## 15. Safety Gates

- No shell=True anywhere
- All new confirmation actions use existing _validate_message()
- All new actions go through existing ALLOWLISTED_ACTION_TYPES check
- Self-healing agents accessed via HTTP only (no docker exec/restart)
- Skill/auditor/learning writes require CONFIRM step
- Mode routing has no execution — read-only analysis only
