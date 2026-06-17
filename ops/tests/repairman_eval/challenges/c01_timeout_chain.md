# Challenge C01 — Timeout Chain Trace

## Error log

```
2026-05-03 11:47:22 ERROR aims.logi_orchestrator — step 3 failed: timeout calling doci_compose
```

## Your task

1. Identify every file and every variable that controls the timeout for the `doci_compose` call.
2. Trace the full chain from the orchestrator's call to the final HTTP request inside DociAgent.
3. Explain why increasing `timeout_s` in `tool_registry.py` is not enough on its own if DociAgent itself spawns a subprocess.
4. Propose a minimal patch (diff format) that ensures the timeout is consistent end-to-end.

## What we're testing

- Can you read `logi/tool_registry.py` → `call_tool()` → `httpx.Client(timeout=timeout)` ?
- Can you trace how `timeout_s` becomes the httpx argument (single float = connect+read)?
- Do you understand that `doci_agent.py` → `doc_agent.py` → `DocAgent.generate()` has its own internal Ollama HTTP call with a separate timeout?
- Can you find the default Ollama timeout in `doc_agent.py` and see if it is shorter than `tool_registry.py`'s timeout?

## Grading

| Criterion | Points |
|-----------|--------|
| Correct file list (tool_registry.py, doci_agent.py, doc_agent.py) | 20 |
| Correct call chain (call_tool → httpx → /compose_and_generate → DocAgent → ollama) | 25 |
| Identifies that httpx single-float = all timeout phases | 15 |
| Finds Ollama timeout in doc_agent._generate_ollama() or equivalent | 20 |
| Patch is minimal and correct | 20 |
| **Total** | **100** |
