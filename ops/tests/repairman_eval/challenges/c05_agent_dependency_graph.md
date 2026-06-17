# Challenge C05 — Agent Dependency Graph Under Partial Failure

## Scenario

ArgusAgent reports: `knomi_agent :8002 DOWN`.

The team wants to know:
- Which pipeline steps are blocked?
- Which can still run with degraded quality?
- Can omi_search substitute for knomi_search in any way?
- What is the correct self-healing action for NemoClaw to dispatch?

## Your task

1. Draw (in text/table) the AIMS V2 agent dependency graph. For each of the
   9 agents, list which other agents it calls and which call it.
2. Identify which of the 7 pipeline steps depend on `knomi_agent`.
3. Explain what `context_filter` does when it receives 0 results from knomi_search
   (trace into `logi/context_filter.py`).
4. Determine whether `omi_search` (port 8008) can substitute for `knomi_search`
   as a fallback. Read both agents' search implementations and compare the
   result schemas.
5. Write the poli_check + mainy_execute call sequence NemoClaw should dispatch
   to restart knomi_agent, including correct `action_type`, `params`, and
   `requester` fields.

## What we're testing

- Full agent topology knowledge
- Understanding of graceful degradation vs hard stop
- context_filter.py behavior with empty input
- omi_search vs knomi_search schema compatibility
- Correct tool call construction for self-healing loop

## Grading

| Criterion | Points |
|-----------|--------|
| Correct dependency graph (all 9 agents, correct directions) | 20 |
| Identifies steps 1-2 as blocked, rest as proceeding with empty filtered_docs | 15 |
| Correctly describes context_filter behavior on empty input | 15 |
| Correct schema comparison between omi_search and knomi_search results | 20 |
| Correct poli_check + mainy_execute payload (all required fields) | 30 |
| **Total** | **100** |
