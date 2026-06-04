from __future__ import annotations


def central_boundary() -> dict:
    return {
        "central_allowed": [
            "approval_aggregation",
            "shared_skill_registry",
            "safety_gates",
            "audit_evidence_indexing",
            "axi_visibility",
            "cross_agent_reporting",
        ],
        "central_forbidden": [
            "mass_runner_owns_all_learning",
            "self_approval",
            "silent_permission_expansion",
            "bypass_agent_loop_pace",
            "bypass_owner_binding",
        ],
        "central_runner_created": False,
    }
