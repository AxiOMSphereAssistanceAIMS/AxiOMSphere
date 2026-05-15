# AIMS — Code Search (Symbol · File · Pattern · Call Graph)

Search target: **$ARGUMENTS**

---

## Phase 0 — Parse query

From `$ARGUMENTS` determine:
- **mode**: `symbol` | `file` | `pattern` | `usage` | `callers` | `auto` (default)
- **scope**: full repo (default) | specific subtree (e.g. `ops/agents/`, `ops/tests/`)
- **target**: function name, class, import, path fragment, regex

---

## Phase 1 — Locate

### 1a. Symbol / function / class definition

```bash
cd /home/axi_omi_sphere/aims-workspace
grep -rn "def $ARGUMENTS\|class $ARGUMENTS" ops/ core/ --include="*.py" | head -40
```

### 1b. All usages / call sites

```bash
grep -rn "$ARGUMENTS" ops/ core/ --include="*.py" | grep -v "^Binary" | head -60
```

### 1c. File by name fragment

```bash
find . -name "*$ARGUMENTS*" -not -path "./.venv*" -not -path "./node_modules*" 2>/dev/null | head -30
```

### 1d. Import map — who imports this module

```bash
grep -rn "import $ARGUMENTS\|from $ARGUMENTS" ops/ core/ --include="*.py" | head -30
```

### 1e. Test coverage — which tests exercise this symbol

```bash
grep -rn "$ARGUMENTS" ops/tests/ --include="*.py" | head -20
```

---

## Phase 2 — Summarise findings

For each hit:
- File path + line number
- Context snippet (function signature or class header)
- Role of this symbol in AIMS (from CLAUDE.md / PLAN.md if known)

---

## Phase 3 — Output contract

```json
{
  "query": "$ARGUMENTS",
  "mode": "<symbol|file|pattern|usage>",
  "hits": [
    {"file": "<path>", "line": 0, "snippet": "<1-line context>"}
  ],
  "total_hits": 0,
  "tests_that_exercise_target": ["<test file>"],
  "slot_used": "32"
}
```
