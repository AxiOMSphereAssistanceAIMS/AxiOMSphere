"""Evidence-bound policy and repair-restart contracts.

This package contains pure contract validators and projections. Persistence and
execution remain owned by the existing AIMS Repairman, Poli, Logi and Telegram
stores.
"""

from .contracts import (
    ContractError,
    build_attestation,
    build_change_proposal,
    build_owner_approval,
    build_permit,
    build_revalidation,
    build_restart_record,
    canonical_digest,
    validate_attestation,
    validate_permit,
    validate_owner_approval,
    validate_revalidation,
    validate_restart_record,
)

__all__ = [
    "ContractError", "build_attestation", "build_change_proposal",
    "build_owner_approval", "build_permit", "build_revalidation",
    "build_restart_record", "canonical_digest", "validate_attestation",
    "validate_permit", "validate_owner_approval", "validate_revalidation",
    "validate_restart_record",
]
