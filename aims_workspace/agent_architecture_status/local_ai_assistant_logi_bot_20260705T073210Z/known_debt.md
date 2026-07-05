# Known Debt — Logi Assistant Gateway

## PATCH_EXECUTION_INTENT_FALSE_POSITIVE

**Status:** Non-blocking — released with this debt recorded.

**Problem:** `deploy` keyword in `ops/agents/m10_safety_adapter._EXECUTION_RE` triggers
`REQUIRES_CONFIRMATION` on passive/read-only Telegram queries.

**Examples that incorrectly require confirmation:**
- "Логи, покажи deploy status"
- "/logi check deployment status"
- "Логи, есть ли сегодня deploy?"
- "Логи, что с последним restart?"

**Examples that correctly require confirmation (must keep):**
- "Логи, deploy новую версию"
- "/logi restart scheduler"
- "Логи, запусти training"
- "Логи, исправь Redis scheduler"

**Root cause:** `_EXECUTION_RE` matches `\bdeploy\b` without distinguishing imperative
("deploy X") from passive ("deploy status"). Same for `restart` and `run`.

**Recommended fix (PATCH_EXECUTION_INTENT_FALSE_POSITIVE):**
Replace bare keyword match with imperative-verb detection. The pattern should only
fire when the keyword is used as a verb in imperative form, not as a noun in status
queries. Possible approach: require the keyword to be followed by a direct object
(not "status"/"статус"/"check"/"покажи"), or add a passive-context exclusion:

```python
_PASSIVE_CONTEXT_RE = re.compile(
    r"\b(status|статус|check|покажи|что\s+с|последн\w+|есть\s+ли)\b",
    re.IGNORECASE,
)

# In check_m10_safety: before the execution guard, check:
if _EXECUTION_RE.search(text) and _PASSIVE_CONTEXT_RE.search(text):
    pass  # passive query — don't treat as execution intent
```

**Do not:** Rewrite LogiAgent. Do not expand scope. Do not replace ai_intent_router/
syntax_interpreter/syntax_policy.

**File to patch:** `ops/agents/m10_safety_adapter.py`
**Test to add:** test that "Логи, покажи deploy status" is NOT blocked by M10
