"""
DOCSREG Auditor Input Contract Validation.

Enforces document_text_len >= 1200 chars before invoking ClaudeCodeRunnerAuditor.
Fail-closed: rejected manifests return {"status": "COMPONENT_BLOCKED", "quality": 0.0}.
"""

import logging

_log = logging.getLogger("docsreg_auditor_input_contract")

# Minimum document length for auditor acceptance
MIN_DOCUMENT_TEXT_LEN = 1200
_REJECTION_QUALITY = 0.0


def validate_manifest_for_auditor(manifest: dict, document_type: str) -> tuple[bool, str]:
    """
    Validate manifest input contract before auditor invocation.

    Parameters
    ----------
    manifest : dict
        Manifest passed to auditor_fn.
    document_type : str
        Document type identifier (for logging).

    Returns
    -------
    (is_valid, rejection_reason) : tuple[bool, str]
        - (True, "") if manifest passes validation
        - (False, reason) if manifest fails; reason describes violation
    """
    if not isinstance(manifest, dict):
        reason = f"manifest must be dict, got {type(manifest).__name__}"
        _log.warning(
            "validate_manifest_for_auditor: %s — document_type=%r",
            reason,
            document_type,
        )
        return False, reason

    doc_text = manifest.get("document_text", "")
    if not isinstance(doc_text, str):
        reason = (
            f"manifest['document_text'] must be str or absent, got {type(doc_text).__name__}"
        )
        _log.warning(
            "validate_manifest_for_auditor: %s — document_type=%r",
            reason,
            document_type,
        )
        return False, reason

    doc_text_len = len(doc_text)

    # Reject whitespace-only documents before length check
    if not doc_text.strip():
        reason = (
            f"document_text_whitespace_only: document_text_len={doc_text_len}; "
            "document_text contains only whitespace (no substantive content)"
        )
        _log.warning(
            "validate_manifest_for_auditor: %s — document_type=%r",
            reason,
            document_type,
        )
        return False, reason

    if doc_text_len < MIN_DOCUMENT_TEXT_LEN:
        reason = (
            f"document_text_len={doc_text_len} < {MIN_DOCUMENT_TEXT_LEN}; "
            "manifest lacks sufficient content for auditor"
        )
        _log.warning(
            "validate_manifest_for_auditor: %s — document_type=%r",
            reason,
            document_type,
        )
        return False, reason

    _log.debug(
        "validate_manifest_for_auditor PASS: document_type=%r document_text_len=%d",
        document_type,
        doc_text_len,
    )
    return True, ""


def rejection_result(rejection_reason: str) -> dict:
    """
    Return fail-closed auditor result for rejected manifest.

    Parameters
    ----------
    rejection_reason : str
        Reason for rejection (included in notes).

    Returns
    -------
    dict
        Auditor-compatible result: {"status": "COMPONENT_BLOCKED", "quality": 0.0, ...}
    """
    return {
        "status": "COMPONENT_BLOCKED",
        "quality": _REJECTION_QUALITY,
        "notes": f"input_contract_rejection: {rejection_reason}",
        "error": None,
    }
