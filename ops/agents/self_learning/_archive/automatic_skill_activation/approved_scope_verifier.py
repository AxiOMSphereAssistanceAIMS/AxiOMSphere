from __future__ import annotations

ALLOWED_AUTO_ACTIVATION_PERMISSION = {
    "ADVISORY_ONLY",
    "READ_ONLY_ANALYSIS",
    "SYNTHETIC_SANDBOX_EXECUTION",
    "CONTROLLED_RUNTIME_USE",
}


def _normalize_text_items(items: list[str]) -> set[str]:
    return {str(i).strip().lower() for i in items if str(i).strip()}


def verify_scope(scope: dict, pack: dict, candidate: dict) -> dict:
    blocked = []

    if scope.get("approved_permission_level") not in ALLOWED_AUTO_ACTIVATION_PERMISSION:
        blocked.append("permission level not allowed for auto activation")

    pack_actions = _normalize_text_items(list(pack.get("instructions", [])))
    approved_actions = _normalize_text_items(list(scope.get("approved_actions", [])))
    if approved_actions and not pack_actions.issubset(approved_actions):
        blocked.append("pack actions exceed approved actions")

    # Check only requested action/instruction text from generated artifacts.
    # Do not scan the full scope object, otherwise the forbidden list itself
    # would self-trigger false positives.
    forbidden = _normalize_text_items(list(scope.get("forbidden_actions", [])))
    candidate_actions = _normalize_text_items(
        [*list(pack.get("instructions", [])), *list(candidate.get("proposed_instructions", []))]
    )
    for a in candidate_actions:
        if a in forbidden:
            blocked.append("forbidden action requested")
            break

    # Controlled runtime activation is allowed only when explicitly approved.
    if (
        scope.get("approved_permission_level") == "CONTROLLED_RUNTIME_USE"
        and "activate within approved controlled runtime scope after full test pass" not in approved_actions
    ):
        blocked.append("controlled runtime activation not present in approved_actions")

    return {
        "scope_verification_passed": len(blocked) == 0,
        "blocking_reasons": blocked,
        "scope_expansion_detected": any("exceed" in b or "permission" in b for b in blocked),
    }
