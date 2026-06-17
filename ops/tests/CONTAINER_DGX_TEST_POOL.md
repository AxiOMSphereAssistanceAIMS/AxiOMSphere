# Пул проверок: контейнеры и DGX (Llama 3.3 70B, `axi_omi_sphere`)

Цель: убедиться, что каждый сервис, который может звать LLM, реально достигает DGX при доступности и даёт приемлемое качество.

## Предусловия

- На DGX запущен Ollama, модель `axi_omi_sphere` в `ollama list`.
- С хоста/контейнера: `curl -sS http://<DGX_IP>:11434/api/tags` → есть `axi_omi_sphere`.

## Матрица

| Сервис | Переменные (ключевые) | Как проверить |
|--------|------------------------|---------------|
| **omi-api** | `OMI_MODEL`, `DGX_*`, `OLLAMA_LOCAL_URL` | Запрос к API чата/агента (см. `omi_agent`), ответ без таймаута; в логах база = DGX при LAN. |
| **omi-bot** | `OMI_LLM_BACKEND=httpx`, `OMI_MODEL` | Сообщение в Telegram боту Omi → ответ от 70B. |
| **omi-maintenance** | как omi-api | Задачи maintenance, если дергают LLM. |
| **omi-register** | `OMI_OLLAMA_MODEL`, `OMI_MODEL` | Регистрация/онбординг с текстовым LLM-шагом. |
| **axi-bot** | `AXI_CHAT_PRIMARY_LLM=ollama`, `AXI_OLLAMA_MODEL`, `DGX_*` | Обычный диалог без веб-поиска → Ollama; с явным поиском → Gemini (если ключи). |
| **axi-bot intent** | `AXI_INTENT_LLM=ollama` | Лог `axi_intent`: сначала Ollama, при ошибке — Gemini. |
| **job-filter-bot** | `JOB_FILTER_LLM_BASE_URL=` (пусто); в коде дефолты `axi_omi_sphere` и **180s** таймаут | Можно не задавать `JOB_FILTER_LLM_*` в `.env`, если устраивают дефолты. |
| **cv-intel-bot** | `CV_INTEL_MODEL`, цепочка `DGX_*` | `curl -sS http://127.0.0.1:8768/health`; CV: `POST /v1/cv/map` (text/plain или JSON `{"text":"..."}`). |
| **registry_llm_audit** | скрипт `/ops/registry_llm_audit.py` | **По запросу:** `docker compose --profile manual run --rm registry-llm-audit` (сервис в compose, не демон). **По расписанию:** раз в неделю окно **воскресенье 01:00–07:59 Asia/Dubai** внутри **`omi-maintenance`** → `report/registry_llm_audit_weekly_*.json`. Отключить: `REGISTRY_LLM_AUDIT_ENABLED=0`. |
| **ollama (локальный)** | — | Резерв; при недоступности DGX цепочка уходит сюда. |

## Быстрые команды из контейнера

```bash
docker compose exec omi-api python -c "
from ops import ollama_resolve
print('omi', ollama_resolve.effective_ollama_base_url())
"
docker compose exec axi-bot python -c "
from ops import ollama_resolve
print('axi', ollama_resolve.effective_ollama_base_url())
"
docker compose exec job-filter-bot python -c "
from ops import ollama_resolve
print('jf', ollama_resolve.effective_job_filter_llm_base_url())
"
```

## Разовый аудит реестра (дубликаты / имена / разделы)

Не изменяет БД — только JSON с рекомендациями. Опционально приложите `.docx` отчёта реестра как контекст структуры.

### In English (what you are asking the tool to do)

In plain terms, **`registry_llm_audit.py` is a read-only pass over `aims_registry.db`** that uses the LLM to:

- **Duplicates** — find groups of rows that are likely the **same document or revision** (by title/summary/meaning, not only filename; anonymized names are expected).
- **Integrity (naming)** — flag **file names that do not match the described content** (filename vs context).
- **Integrity (placement)** — suggest **correct or missing `aims_process` / `aims_element`** when a document sits in the wrong section of the AIMS hierarchy.

So phrases like *“check the database for duplicates”* or *“audit registry integrity”* describe the same run. Output is **recommendations only**; merge, delete, register master, and anonymization stay manual.

```bash
docker compose run --rm --no-deps \
  -v "$(pwd)/aims_workspace:/data" -v "$(pwd)/ops:/ops" -v "$(pwd)/ops/omi_telegram:/omi_telegram" \
  -e PYTHONPATH=/ops:/omi_telegram \
  -e OLLAMA_BASE_URL= -e DGX_OLLAMA_URL=http://192.168.72.225:11434 \
  axiomsphere-axi-bot:local \
  python /ops/registry_llm_audit.py --db /data/aims_registry.db --docx /data/AIMS_Registry_Report_test.docx
```

Replace `AIMS_Registry_Report_test.docx` with your report file under `aims_workspace/` (e.g. `AIMS_Registry_Report_20260403_121644.docx`). Omit `--docx ...` if you have no DOCX hint; the audit still runs on DB rows only.

**On-demand (compose service, same image as Omi):**

```bash
docker compose --profile manual run --rm registry-llm-audit
```

**On-demand (без отдельного сервиса, из уже запущенного maintenance):**

```bash
docker compose exec omi-maintenance python /ops/registry_llm_audit.py --db /data/aims_registry.db --docx-latest
```

Скрипт **не меняет SQLite**; «исправления» дубликатов по содержимому — отдельно: ежемесячный **`task_deduplication` / night dedup** в `omi_maintenance` (по `content_hash`), еженедельный **`PRAGMA integrity_check`** — целостность файла БД.

## Качество (субъективно)

Для каждого сервиса: 3–5 типовых промптов (краткий ответ, структурированный JSON, RAG-контекст, длинный отчёт). Сравнить с предыдущей моделью (qwen/Gemini) по точности и следованию формату.
