from __future__ import annotations

PASS_STATES = {"HERMES_SANDBOX_PASS", "HERMES_SANDBOX_WARN_PASS"}


def is_pass_like(result_status: str) -> bool:
    return result_status in PASS_STATES
