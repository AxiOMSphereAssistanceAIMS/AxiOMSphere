"""Capability gap assessor for the Logi universal orchestrator.

When a tool call fails because a service is unavailable or a capability
is missing, this module produces a structured gap report that describes
what is needed to close the gap — suitable for display to the user and
as an OmniRoute search query.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("aims.logi.capability_assessor")

# Known service → pip packages mapping (best-effort)
_SERVICE_PACKAGES: dict[str, list[str]] = {
    "qdrant": ["qdrant-client"],
    "redis": ["redis", "hiredis"],
    "knomi": ["sentence-transformers", "qdrant-client"],
    "poli": [],
    "traini": ["peft", "bitsandbytes", "trl"],
    "repairman": [],
    "argus": [],
}

# Error patterns → human-readable cause
_ERROR_CAUSES = {
    "connection refused": "service is not running or not reachable at that address",
    "name or service not known": "hostname cannot be resolved — service may not be deployed",
    "timeout": "service is reachable but not responding in time — may be overloaded or starting up",
    "404": "endpoint does not exist — service may be running an older version",
    "500": "service returned an internal error — check service logs",
    "503": "service is unavailable — may be starting up or circuit-breaker tripped",
    "no such container": "Docker container is not running — use docker_control start to launch it",
    "no such image": "Docker image is missing — image needs to be built or pulled",
}


@dataclass
class CapabilityGap:
    tool_name: str
    task_description: str
    error_message: str
    error_cause: str = ""
    pip_packages: list[str] = field(default_factory=list)
    apt_packages: list[str] = field(default_factory=list)
    docker_services: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    config_steps: list[str] = field(default_factory=list)
    implementation_steps: list[str] = field(default_factory=list)
    omniroute_search_query: str = ""
    severity: str = "medium"  # low | medium | high | critical

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_gap": {
                "tool": self.tool_name,
                "task": self.task_description,
                "error": self.error_message,
                "cause": self.error_cause,
                "severity": self.severity,
            },
            "tools_needed": {
                "pip": self.pip_packages,
                "apt": self.apt_packages,
            },
            "services_needed": self.docker_services,
            "config_needed": self.env_vars,
            "implementation_steps": self.implementation_steps,
            "omniroute_search_query": self.omniroute_search_query,
        }

    def to_text(self) -> str:
        lines = [
            f"**Capability gap detected** [{self.severity.upper()}]",
            f"Tool: `{self.tool_name}`",
            f"Task: {self.task_description}",
            f"Error: {self.error_message}",
        ]
        if self.error_cause:
            lines.append(f"Cause: {self.error_cause}")
        if self.pip_packages:
            lines.append(f"Pip packages needed: {', '.join(self.pip_packages)}")
        if self.apt_packages:
            lines.append(f"Apt packages needed: {', '.join(self.apt_packages)}")
        if self.docker_services:
            lines.append(f"Docker services to start: {', '.join(self.docker_services)}")
        if self.env_vars:
            lines.append(f"Env vars needed: {', '.join(self.env_vars)}")
        if self.implementation_steps:
            lines.append("Steps to resolve:")
            for i, step in enumerate(self.implementation_steps, 1):
                lines.append(f"  {i}. {step}")
        if self.omniroute_search_query:
            lines.append(f"Search query: {self.omniroute_search_query}")
        return "\n".join(lines)


def _classify_error(error: str) -> tuple[str, str]:
    """Return (cause_description, severity)."""
    err_lower = error.lower()
    for pattern, cause in _ERROR_CAUSES.items():
        if pattern in err_lower:
            severity = "high" if "refused" in err_lower or "not running" in err_lower else "medium"
            return cause, severity
    return "unknown failure", "medium"


def _infer_docker_service(tool_name: str, error: str) -> list[str]:
    """Guess which Docker service needs to be started based on tool name and error."""
    service_map = {
        "knomi_search": ["knomi-agent"],
        "doci_compose": ["doc-agent"],
        "omi_store": ["omi-api", "task-registry"],
        "omi_search": ["omi-api", "task-registry"],
        "cloud_validate": ["omi-quality-gate"],
        "poli_check": ["poli-agent"],
        "mainy_execute": ["mainy-repair-agent"],
        "argus_health": ["argus-bot"],
        "traini_trigger": ["traini-agent"],
        "repairman_trigger": ["repairman-api"],
    }
    return service_map.get(tool_name, [])


def _infer_env_vars(tool_name: str, error: str) -> list[str]:
    env_map = {
        "cloud_validate": ["NVIDIA_API_KEY", "OMNIROUTE_BASE_URL", "OMNI_TOKEN"],
        "repairman_trigger": ["AIMS_SERVICE_TOKEN", "AIMS_REPAIR_MODEL"],
        "poli_check": ["AIMS_SERVICE_TOKEN"],
        "mainy_execute": ["AIMS_SERVICE_TOKEN"],
        "traini_trigger": ["AIMS_SERVICE_TOKEN"],
    }
    return env_map.get(tool_name, [])


def assess_gap(
    tool_name: str,
    task_description: str,
    error: str,
) -> CapabilityGap:
    """Produce a structured gap assessment for a failed tool call."""
    cause, severity = _classify_error(error)
    docker_services = _infer_docker_service(tool_name, error)
    env_vars = _infer_env_vars(tool_name, error)
    pip_packages = _SERVICE_PACKAGES.get(tool_name, [])

    steps: list[str] = []
    if docker_services:
        steps.append(
            f"Start Docker service(s): docker compose up -d {' '.join(docker_services)}"
        )
    if env_vars:
        steps.append(f"Set environment variables in .env: {', '.join(env_vars)}")
    if pip_packages:
        steps.append(f"Install Python packages: pip install {' '.join(pip_packages)}")
    if not steps:
        steps.append(f"Investigate service '{tool_name}': check logs and configuration")
        steps.append("Run: docker compose ps  to see which containers are up")
        steps.append("Run: docker compose logs <service>  to inspect errors")

    search_query = (
        f"AIMS {tool_name} service unavailable: {cause}. "
        f"Task: {task_description[:120]}. Error: {error[:120]}"
    )

    gap = CapabilityGap(
        tool_name=tool_name,
        task_description=task_description,
        error_message=error,
        error_cause=cause,
        pip_packages=pip_packages,
        docker_services=docker_services,
        env_vars=env_vars,
        implementation_steps=steps,
        omniroute_search_query=search_query,
        severity=severity,
    )

    log.info(
        "capability_gap tool=%s severity=%s cause=%s services=%s",
        tool_name, severity, cause, docker_services,
    )
    return gap


def is_connectivity_error(error: str) -> bool:
    """Return True if the error looks like a network/service-unavailable error."""
    if not error:
        return False
    indicators = [
        "connection refused", "timed out", "timeout", "name or service not known",
        "no route to host", "eof", "broken pipe", "503", "502",
    ]
    err_lower = error.lower()
    return any(ind in err_lower for ind in indicators)


def assess_gap_from_tool_result(
    tool_name: str,
    task_description: str,
    result: dict[str, Any],
) -> CapabilityGap | None:
    """Return a CapabilityGap if the tool result looks like a connectivity failure, else None."""
    error = result.get("error", "")
    if error and is_connectivity_error(error):
        return assess_gap(tool_name, task_description, error)
    return None
