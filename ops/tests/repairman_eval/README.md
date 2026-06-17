# AIMS Repairman Evaluation Suite

Tests whether Claude Code (as Engineering Repair Tool) can correctly read and diagnose issues in the AIMS V2 codebase — including cross-agent connections, data flow, and env var chains.

## Pass threshold: 70/100 per challenge, 70% overall

## Challenges

| ID | Title | What It Tests |
|----|-------|---------------|
| C01 | Timeout chain trace | tool_registry → httpx → doci_agent → ollama timeout chain |
| C02 | Preview truncation → false compliance FAIL | doci_agent 800-char cap → orchestrator → cloud_validate |
| C03 | Env var chain: Ollama URL routing | DOC_AGENT_OLLAMA_BASE priority chain, ollama_resolve fallback |
| C04 | Silent failure in step 6 (OmiStore) | Discarded call_tool() return value in orchestrator step 6 |
| C05 | Agent dependency graph under partial failure | Full 9-agent topology, self-healing poli+mainy call |
| C06 | Training loop: why doesn't it fire? | check_training_triggers() never called automatically |

## Running

```bash
# All challenges (requires gateway running on :8082 with Nemotron)
python3 ops/tests/repairman_eval/eval_repairman.py

# Single challenge
python3 ops/tests/repairman_eval/eval_repairman.py --challenge c02

# JSON output for CI
python3 ops/tests/repairman_eval/eval_repairman.py --json
```

## Prerequisites

1. Gateway running: `uvicorn ops.gateway.anthropic_proxy:app --host 127.0.0.1 --port 8082`
2. Ollama running with `nemotron-3-super:120b` loaded
3. Source env: `source ops/claude_code/env.repairman`

## Scoring method

Heuristic keyword matching in the repairman's response. Each challenge has 5 criteria,
each worth 10-30 points. Partial credit is not awarded per criterion (hit/miss).

A repairman that passes all 6 challenges at ≥70% demonstrates:
- Can trace multi-file call chains
- Understands agent-to-agent data contracts
- Can read env var resolution logic
- Produces minimal, correct patches
- Understands the full 7-step pipeline topology
