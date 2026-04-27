# DocAgent Demo — Step-by-Step

## Scenario: Job Safety Analysis for Confined Space Entry

**Total time:** ~10 minutes end-to-end (dual pipeline)

### Step 1 — Engineer sends request

In Telegram, engineer types to Axi Bot:

```
/doc Create a Job Safety Analysis for confined space entry at an underground mine.
Reference ISO 45001. Include hazard table, controls hierarchy, permit conditions.
```

### Step 2 — Axi routes to DocAgent

Axi Bot detects document generation intent and calls `POST /generate` on DocAgent (localhost:8100):

```json
{
  "user_request": "Create a Job Safety Analysis...",
  "dual_pipeline": true
}
```

### Step 3 — qwen3-32B drafts the document (~5 min)

qwen3:32b generates a structured JSA with:
- Scope and applicability
- Hazard identification table (confined space specific)
- Risk controls hierarchy (Elimination → Substitution → Engineering → Admin → PPE)
- Permit-to-work conditions
- Emergency response procedure
- ISO 45001 §8.1.3 references

### Step 4 — Qwen-72B formats (~3 min)

qwen3:32b converts the draft to professional `.docx` format:
- Proper headings, tables, numbered sections
- Document header with revision, date, author placeholders
- ISO-aligned section numbering

### Step 5 — Gemini scores (~15 sec)

Gemini Flash evaluates against ISO 45001, returns:

```json
{"score": 0.84, "feedback": "Document covers all required JSA sections with complete hazard controls matrix and permit conditions referencing ISO 45001 §8.1.3."}
```

Score ≥ 0.8 → approved. Document saved to `gold_pairs.jsonl` for fine-tuning.

### Step 6 — Delivery

Axi Bot sends the `.docx` file to the Telegram chat:

```
✅ JSA готов (ISO compliance: 84%)
📄 JSA_confined_space_entry_20260419.docx

Feedback: Document covers all required JSA sections with complete hazard 
controls matrix and permit conditions referencing ISO 45001 §8.1.3.
```

Engineer downloads, reviews, signs off. Total elapsed: **~8 min 30 sec**.

---

## CLI Demo (no Telegram)

```bash
cd examples
export GEMINI_API_KEY=your_key
export DOCAGENT_URL=http://localhost:8100
python doc_agent_example.py
```

Expected output:
```
Sending request to DocAgent (http://localhost:8100)...

Document: /data/JSA_confined_space_entry.docx
ISO compliance score: 84%
Feedback: Document covers all required JSA sections...
Preview:
JOB SAFETY ANALYSIS
Confined Space Entry — Underground Mining Operations
...

Completed in 512s
Result saved to training data (gold pair).
```
