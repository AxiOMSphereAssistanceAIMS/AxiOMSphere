"""Service authentication for internal AIMS APIs.

All write/execute endpoints require Bearer token in Authorization header.
Token value is AIMS_SERVICE_TOKEN env var (default: "aims-service-token").
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

SERVICE_TOKEN: str = os.getenv("AIMS_SERVICE_TOKEN", "aims-service-token")


def verify_service_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI Depends function for protected endpoints.

    Raises HTTPException(401) if Authorization header is missing or incorrect.
    """
    if authorization != f"Bearer {SERVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="service token required")


def service_headers() -> dict[str, str]:
    """Returns Authorization header dict for calling protected endpoints."""
    return {"Authorization": f"Bearer {SERVICE_TOKEN}"}
