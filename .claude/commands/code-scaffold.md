# AIMS — Code Scaffold (New Agent · Worker · Test · Skill)

Scaffold target: **$ARGUMENTS**

_This skill runs on slot 120 (nemotron-3-super:120b) for architecture-quality output._

---

## Phase 0 — Parse request

From `$ARGUMENTS` determine:
- **type**: `agent` | `worker` | `test` | `skill` | `api-endpoint` | `ft-config`
- **name**: component name (snake_case)
- **role**: one-sentence description of what this component does

---

## Phase 1 — Architecture check

Before generating any file, verify:

```bash
cd /home/axi_omi_sphere/aims-workspace

# Existing agents (avoid naming collision)
ls ops/agents/

# Existing workers
ls ops/workers/

# Existing tests
ls ops/tests/ | sort

# Existing skills (Claude Code commands)
ls .claude/commands/

# Constitution constraints — check for invariants
grep -n "invariant\|NEVER\|FORBIDDEN\|must not" PROJECT_CONSTITUTION.md 2>/dev/null | head -20
```

---

## Phase 2 — Agent scaffold

Template for a new AIMS agent (`ops/agents/<name>_agent.py`):

```python
"""<Name>Agent — <one-sentence role>."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


class <Name>Agent:
    """<Role description>."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        logger.info("<Name>Agent initialised")

    async def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process an event and return a structured response."""
        raise NotImplementedError

    def health(self) -> dict[str, str]:
        return {"status": "ok", "agent": "<name>"}
```

Conventions:
- No hardcoded model names — use `resolve_slot("N")`
- No direct DB writes — go through `aims_registry.db` via the registry API
- PoliAgent gate required for any destructive action
- Every public method has a structured return dict

---

## Phase 3 — Worker scaffold

Template for a new AIMS worker (`ops/workers/<name>_worker.py`):

```python
"""<Name>Worker — <role>."""
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)


class <Name>Worker:
    def __init__(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("<Name>Worker started")
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("<Name>Worker tick failed")
            await asyncio.sleep(60)

    async def _tick(self) -> None:
        pass

    def stop(self) -> None:
        self._running = False
```

---

## Phase 4 — Test scaffold

Template for `ops/tests/test_<name>.py`:

```python
"""Tests for <name>."""
import sys
import pytest

sys.path.insert(0, 'ops')


@pytest.fixture
def agent():
    from agents.<name>_agent import <Name>Agent
    return <Name>Agent()


def test_<name>_health(agent):
    result = agent.health()
    assert result["status"] == "ok"


def test_<name>_basic(agent):
    # TODO: add meaningful test
    pass


@pytest.mark.integration
def test_<name>_with_ollama(agent):
    """Requires RUN_OLLAMA_INTEGRATION=1."""
    import os
    if not os.getenv("RUN_OLLAMA_INTEGRATION"):
        pytest.skip("Set RUN_OLLAMA_INTEGRATION=1 to run")
    # integration test here
```

---

## Phase 5 — Skill scaffold

Template for `.claude/commands/<name>.md`:

```markdown
# AIMS — <Title> (<Tag1> · <Tag2>)

Target: **$ARGUMENTS**

---

## Phase 0 — Parse request
...

## Phase N — Output contract

json
{
  "target": "$ARGUMENTS",
  "result": "<>",
  "slot_used": "32"
}

```

---

## Phase 6 — Write and verify

After generating file content:

```bash
# Verify Python syntax
python3 -m py_compile ops/agents/<name>_agent.py 2>&1

# Verify test imports
python3 -m pytest ops/tests/test_<name>.py --collect-only 2>&1 | head -20
```

---

## Phase 7 — Output contract

```json
{
  "target": "$ARGUMENTS",
  "type": "agent|worker|test|skill|api-endpoint|ft-config",
  "files_created": ["<path>"],
  "syntax_ok": true,
  "imports_ok": true,
  "test_collected": true,
  "constitution_violations": 0,
  "slot_used": "120"
}
```
