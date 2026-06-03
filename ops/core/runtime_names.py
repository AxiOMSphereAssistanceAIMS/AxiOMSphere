"""Single source of truth for AIMS runtime service names and queue keys.

This module provides canonical names used across the AIMS system:
- Docker Compose service names (for restart commands)
- Redis queue keys (for queue operations)
- Container names (for docker ps filtering)

All agents, orchestrators, and repair tools MUST import from this module
instead of hardcoding names.
"""
from __future__ import annotations

from typing import Final

# ── Docker Compose Service Names ──────────────────────────────────────────────
# These are the service names used in docker-compose.yml
# Use these for: docker compose restart <service_name>

SERVICE_AXI_BOT: Final[str] = "axi-bot"
SERVICE_OMI_BOT: Final[str] = "omi-bot"
SERVICE_ARGUS_BOT: Final[str] = "argus-bot"
SERVICE_LOGI_BOT: Final[str] = "logi-bot"
SERVICE_AIMS_API: Final[str] = "aims-api"
SERVICE_AIMS_WORKER: Final[str] = "aims-worker"
SERVICE_AIMS_ORCHESTRATOR: Final[str] = "aims-orchestrator"
SERVICE_QUEUE_API: Final[str] = "queue-api"
SERVICE_TASK_REGISTRY: Final[str] = "task-registry"
SERVICE_DOC_AGENT: Final[str] = "doc-agent"
SERVICE_KNOMI_AGENT: Final[str] = "knomi-agent"
SERVICE_POLI_AGENT: Final[str] = "poli-agent"
SERVICE_MAINY_REPAIR_AGENT: Final[str] = "mainy-repair-agent"
SERVICE_OMI_API: Final[str] = "omi-api"
SERVICE_QDRANT: Final[str] = "qdrant"
SERVICE_AIMS_REDIS: Final[str] = "aims-redis"
SERVICE_SCHEDULE: Final[str] = "schedule"

# All restartable services (used by SysPolic)
RESTARTABLE_SERVICES: Final[frozenset[str]] = frozenset({
    SERVICE_AXI_BOT,
    SERVICE_OMI_BOT,
    SERVICE_ARGUS_BOT,
    SERVICE_LOGI_BOT,
    SERVICE_AIMS_API,
    SERVICE_AIMS_WORKER,
    SERVICE_AIMS_ORCHESTRATOR,
    SERVICE_QUEUE_API,
    SERVICE_TASK_REGISTRY,
    SERVICE_DOC_AGENT,
    SERVICE_KNOMI_AGENT,
    SERVICE_POLI_AGENT,
    SERVICE_MAINY_REPAIR_AGENT,
    SERVICE_OMI_API,
    SERVICE_QDRANT,
    SERVICE_AIMS_REDIS,
    SERVICE_SCHEDULE,
})

# ── Container Names ────────────────────────────────────────────────────────────
# These are the container_name values in docker-compose.yml
# Use these for: docker ps --filter name=<container_name>

CONTAINER_AXI_BOT: Final[str] = "axiomsphere-axi-bot"
CONTAINER_OMI_BOT: Final[str] = "axiomsphere-omi-bot"
CONTAINER_ARGUS_BOT: Final[str] = "axiomsphere-argus-bot"
CONTAINER_LOGI_BOT: Final[str] = "axiomsphere-logi-bot"
CONTAINER_AIMS_API: Final[str] = "axiomsphere-aims-api"
CONTAINER_AIMS_WORKER: Final[str] = "axiomsphere-aims-worker"
CONTAINER_AIMS_ORCHESTRATOR: Final[str] = "axiomsphere-aims-orchestrator"
CONTAINER_QUEUE_API: Final[str] = "axiomsphere-queue-api"
CONTAINER_TASK_REGISTRY: Final[str] = "axiomsphere-task-registry"
CONTAINER_DOC_AGENT: Final[str] = "axiomsphere-doc-agent"
CONTAINER_KNOMI_AGENT: Final[str] = "axiomsphere-knomi-agent"
CONTAINER_POLI_AGENT: Final[str] = "axiomsphere-poli-agent"
CONTAINER_MAINY_REPAIR_AGENT: Final[str] = "axiomsphere-mainy-repair-agent"
CONTAINER_OMI_API: Final[str] = "axiomsphere-omi-api"
CONTAINER_QDRANT: Final[str] = "axiomsphere-qdrant"
CONTAINER_AIMS_REDIS: Final[str] = "axiomsphere-aims-redis"
CONTAINER_SCHEDULE: Final[str] = "axiomsphere-schedule"

# ── Redis Queue Keys ───────────────────────────────────────────────────────────
# Standard queue key names used across AIMS
# Use these for: redis.llen(), redis.lpush(), redis.rpop(), etc.

QUEUE_PENDING: Final[str] = "queue:pending"
QUEUE_PROCESSING: Final[str] = "queue:processing"
QUEUE_FAILED: Final[str] = "queue:failed"
QUEUE_COMPLETED: Final[str] = "queue:completed"

# All standard queues
ALL_QUEUES: Final[frozenset[str]] = frozenset({
    QUEUE_PENDING,
    QUEUE_PROCESSING,
    QUEUE_FAILED,
    QUEUE_COMPLETED,
})

# ── Pipeline Step to Service Mapping ───────────────────────────────────────────
# Maps SupervisedPipeline step names to docker compose service names
# Used by DecisionEngine for targeted restarts

STEP_SERVICE_MAP: Final[dict[str, str | None]] = {
    "knomi_search": SERVICE_KNOMI_AGENT,
    "context_filter": None,  # Pure function, no service
    "doci_compose": SERVICE_DOC_AGENT,
    "cloud_validate": SERVICE_AIMS_API,
    "poli_check": SERVICE_POLI_AGENT,
    "omi_store": SERVICE_OMI_API,
}

# ── Service to Port Mapping ────────────────────────────────────────────────────
# Internal service ports (for health checks and API calls)

SERVICE_PORTS: Final[dict[str, int]] = {
    SERVICE_AIMS_API: 8000,
    SERVICE_QUEUE_API: 8001,
    SERVICE_TASK_REGISTRY: 8002,
    SERVICE_DOC_AGENT: 8003,
    SERVICE_POLI_AGENT: 8004,
    SERVICE_MAINY_REPAIR_AGENT: 8005,
    SERVICE_ARGUS_BOT: 8006,
    SERVICE_KNOMI_AGENT: 8008,
    SERVICE_OMI_API: 8009,
    # 8010 reserved for watchdog-agent
    SERVICE_LOGI_BOT: 8011,
}
