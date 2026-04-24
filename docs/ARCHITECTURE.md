# AIMS Platform — Architecture

## System Overview

AIMS runs as a set of Telegram bots backed by local LLM inference (DGX Spark) and cloud API quality gates.

```
Telegram Groups
      │
      ├── Axi Bot (external reasoning — Gemini API + Anthropic Claude)
      │     └── DocAgent HTTP API (localhost:8100)
      │           ├── deepseek-r1:70b  (Ollama, DGX Spark) — draft
      │           ├── qwen2.5:72b      (Ollama, DGX Spark) — format + revise
      │     │     └── Gemini Flash/Pro (cloud)             — ISO score 0–1
      │
      ├── Omi Bot (registry + OCR — local Qwen 14B)
      │     ├── omi_registry.db   (OCR queue + raw extracts)
      │     └── aims_registry.db  (master document + process store)
      │
      └── Argus Bot (DevOps orchestrator)
            ├── System health monitor (Axi, Omi, R1, Qwen)
            ├── Scheduled plan runner (YAML cron plans)
            └── Digest sender (nightly summaries)
```

## Doc Generation Pipeline (Dual Mode)

```
User request (natural language)
      │
      ▼
deepseek-r1:70b  ←── ISO-aware system prompt
      │ ~5 min     (structural reasoning + outline)
      ▼
qwen2.5:72b      ←── Format to professional .docx structure
      │ ~3 min
      ▼
Gemini Flash     ←── Score against ISO 45001 / 21502 / 82079 / 9001 / API RP 505
      │ ~15 sec    Returns: {"score": 0.0–1.0, "feedback": "..."}
      │
      ├── score ≥ 0.8 → save gold pair → deliver .docx
      ├── score 0.6–0.8 → qwen2.5:72b revise with feedback → re-score
      └── score < 0.6  → retry full pipeline
```

## Hardware

| Component | Hardware | Role |
|-----------|----------|------|
| Inference | NVIDIA DGX Spark | R1-70B + Qwen-72B via Ollama |
| Orchestration | Ubuntu server | Bot processes + Argus scheduler |
| Quality gate | Google Cloud | Gemini Flash/Pro API |
| Fallback reasoning | Anthropic Cloud | Claude (Axi complex queries) |

## Data Layer

| Database | Contents |
|----------|----------|
| `aims_registry.db` | Master documents, processes, project records |
| `omi_registry.db` | OCR queue, raw text extracts from uploaded files |
| `training/gen_v1_pairs.jsonl` | Gold training pairs (score ≥ 0.8) |
| `training/standard_dpo_pairs.jsonl` | DPO pairs (rejected attempt → chosen revision) |

## Security

- All bots verify `chat_id` against allowlist before processing any command
- No external network exposure — DocAgent API binds to `localhost:8100`
- Gemini/Anthropic API keys stored in environment, never logged
- Owner-only commands gated behind `OWNER_CHATS` list
