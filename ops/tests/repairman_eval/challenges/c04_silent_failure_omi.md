# Challenge C04 — Silent Failure in Step 6 (OmiStore)

## Symptom

The pipeline returns `{"status": "success"}` but the document never appears
in the OMI registry. No error is logged.

## Relevant orchestrator code (step 6)

```python
# Step 6: Store as master document
log.info("step 6 — omi_store (master)")
call_tool(
    "omi_store",
    {
        "document": doc_result,
        "status": "master",
        "audit_id": poli.get("audit_id", ""),
    },
)

# Step 7: Return success
log.info("handle_task complete — success")
return {
    "status": "success",
    "document": doc_result,
    ...
}
```

## Your task

1. Identify the exact bug in the orchestrator code above.
2. Check `omi_agent.py` (port 8008) to understand what it returns on failure.
3. Check `call_tool()` in `tool_registry.py` to understand what it returns on error.
4. Propose a minimal patch to step 6 so that omi_store failures are detected
   and reported instead of silently ignored.
5. Decide: should a step 6 failure return `status=error` or `status=success_with_warning`?
   Justify your choice from a document-factory reliability perspective.

## What we're testing

- Do you notice `call_tool()` return value is discarded at step 6?
- Do you know `call_tool()` returns `{"error": "..."}` on failure?
- Do you check what `omi_agent.py` actually responds with?
- Is your proposed fix minimal (2-3 lines) and not over-engineered?

## Grading

| Criterion | Points |
|-----------|--------|
| Identifies the discarded return value as the root cause | 30 |
| Checks call_tool() contract in tool_registry.py | 20 |
| Checks omi_agent.py response schema | 15 |
| Correct minimal patch (capture result, check "error" key) | 25 |
| Justified choice of error vs warning semantics | 10 |
| **Total** | **100** |
