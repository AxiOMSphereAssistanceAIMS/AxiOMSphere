# Challenge C03 — Env Var Chain: Ollama URL Routing

## Symptom

DociAgent uses `http://ollama:11434` (Docker internal hostname) instead of
`http://127.0.0.1:11434`, causing all generation requests to fail on the host.

The fix has already been applied, but a new developer accidentally removed
`DOC_AGENT_OLLAMA_BASE` from `start_aims_v2.sh`. The symptom returns.

## Your task

1. Trace the complete env-var resolution chain that determines the Ollama URL
   used inside `doc_agent.py`. Name every env var checked, in order, and what
   happens if each is unset.
2. Identify the fallback function that ultimately returns `http://ollama:11434`
   and which file it lives in.
3. Explain why `KNOMI_OLLAMA_URL` doesn't fix the issue even though it's exported
   in `start_aims_v2.sh`.
4. Propose a defensive patch so that the correct URL is always used even if
   `DOC_AGENT_OLLAMA_BASE` is accidentally removed from the startup script.

## What we're testing

- Do you find `_ollama_base()` in `doc_agent.py` and read its priority chain?
- Do you find `ollama_resolve.py:resolve_ollama_base_url()` → returns `http://ollama:11434`?
- Do you see that `KNOMI_OLLAMA_URL` is read by `knomi_agent.py`, not `doc_agent.py`?
- Can you propose a fallback (e.g., hardcode localhost in `_ollama_base()` as last resort)?

## Grading

| Criterion | Points |
|-----------|--------|
| Lists all env vars in correct priority order | 20 |
| Identifies `ollama_resolve.py` as source of `http://ollama:11434` default | 25 |
| Explains why KNOMI_OLLAMA_URL is irrelevant for DociAgent | 15 |
| Defensive patch changes the fallback or adds a localhost safety net | 25 |
| Patch is minimal and doesn't break Docker deployments | 15 |
| **Total** | **100** |
