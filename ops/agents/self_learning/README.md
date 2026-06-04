# Self-Learning Subsystem — FROZEN

**Status:** Archived 2026-06-04. Zero runtime usage confirmed.

## Kept (3 files)
- `skill_lifecycle.py` — state machine for future skill promotion
- `skill_registry_schema.py` — data models if we re-activate
- `agent_skill_ownership.py` — ownership mapping

## Archived
Everything in `_archive/` was the over-engineered 6-stage promotion
pipeline (174 files). Can be restored if needed — nothing was deleted.

## To re-activate
Move files from `_archive/` back and wire into EventBus.
