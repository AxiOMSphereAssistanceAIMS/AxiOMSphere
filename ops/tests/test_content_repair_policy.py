from __future__ import annotations


def test_content_repair_policy_plans_missing_required_element_repair():
    from ops.docgen.content_repair_policy import ContentRepairPolicy

    actions = ContentRepairPolicy().plan_repairs(
        self_check_results=[
            {
                "block_id": "SEC-004",
                "status": "WARN",
                "issues": [
                    {
                        "severity": "major",
                        "issue_type": "missing_required_element",
                        "element": "success_criteria",
                    }
                ],
            }
        ]
    )

    assert actions
    assert actions[0].block_id == "SEC-004"
    assert "success_criteria" in actions[0].instruction


def test_content_repair_policy_plans_empty_content_regeneration():
    from ops.docgen.content_repair_policy import ContentRepairPolicy

    actions = ContentRepairPolicy().plan_repairs(
        self_check_results=[
            {
                "block_id": "SEC-001",
                "status": "FAIL",
                "issues": [{"severity": "critical", "issue_type": "empty_content"}],
            }
        ]
    )

    assert actions
    assert "Regenerate" in actions[0].instruction


def test_content_repair_policy_no_issues_no_actions():
    from ops.docgen.content_repair_policy import ContentRepairPolicy

    actions = ContentRepairPolicy().plan_repairs(
        self_check_results=[{"block_id": "SEC-001", "status": "PASS", "issues": []}]
    )
    assert actions == []


def test_content_repair_policy_handles_too_short_and_forbidden():
    from ops.docgen.content_repair_policy import ContentRepairPolicy

    actions = ContentRepairPolicy().plan_repairs(
        self_check_results=[
            {
                "block_id": "SEC-002",
                "status": "WARN",
                "issues": [
                    {"severity": "major", "issue_type": "too_short"},
                    {"severity": "major", "issue_type": "forbidden_element_present", "element": "tbd"},
                ],
            }
        ]
    )
    by_type = {a.issue_type: a for a in actions}
    assert "too_short" in by_type
    assert "Expand" in by_type["too_short"].instruction
    assert "forbidden_element_present" in by_type
    assert "tbd" in by_type["forbidden_element_present"].instruction
