# Challenge C02 — Preview Truncation → False Compliance FAIL

## Error log

```json
{
  "status": "gap_report",
  "gaps": [
    "Document too short: 112 words (minimum 500)",
    "Missing AIMS section: responsibilities",
    "Missing AIMS section: references"
  ]
}
```

The document was generated successfully by Nemotron (step 3 passed). The gap report
came from step 4 (cloud_validate). The actual generated .docx is ~3000 words.

## Your task

1. Find where in the codebase the `document_text` field is populated before it is sent
   to `cloud_validate`. What is the maximum length at that point?
2. Identify which function in `cloud_validation_agent.py` uses `document_text` to count
   words and check sections.
3. Explain the data path: `doci_agent.py:compose_and_generate` → `orchestrator.py:step4`
   → `cloud_validation_agent.py:validate_and_check_compliance`.
4. Propose a fix. Two valid approaches exist — identify both and pick the better one.

## What we're testing

- Do you know that `doci_agent.py:ComposeAndGenerateResponse.preview` is capped at 800 chars?
- Do you trace that `orchestrator.py` sends `document_text=doc_result.get("preview", "")` ?
- Do you find `_check_compliance(document_text, ...)` in cloud_validation_agent?
- Do you understand the `doc_path` field is already available in the response?

## Grading

| Criterion | Points |
|-----------|--------|
| Finds the 800-char cap in doci_agent.py (preview[:800]) | 25 |
| Traces orchestrator.py step 4 sends preview not full text | 25 |
| Identifies doc_path as the solution path | 20 |
| Proposes either: (a) read docx from doc_path, or (b) expand preview size | 20 |
| Patch is correct and minimal | 10 |
| **Total** | **100** |
