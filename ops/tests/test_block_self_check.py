from __future__ import annotations


def test_block_self_check_passes_valid_block():
    from ops.docgen.block_self_check import BlockSelfChecker

    result = BlockSelfChecker().check(
        block={"block_id": "SEC-001", "content": "problem_statement recommendations " * 80},
        block_spec={
            "id": "SEC-001",
            "validation_rules": {
                "required_elements": ["problem_statement", "recommendations"],
                "min_length_words": 50,
            },
        },
    )

    assert result.status == "PASS"
    assert result.score == 1.0


def test_block_self_check_detects_missing_required_element():
    from ops.docgen.block_self_check import BlockSelfChecker

    result = BlockSelfChecker().check(
        block={"block_id": "SEC-001", "content": "generic text " * 80},
        block_spec={
            "id": "SEC-001",
            "validation_rules": {
                "required_elements": ["problem_statement"],
                "min_length_words": 50,
            },
        },
    )

    assert result.status == "WARN"
    assert any(issue["issue_type"] == "missing_required_element" for issue in result.issues)


def test_block_self_check_detects_empty_content():
    from ops.docgen.block_self_check import BlockSelfChecker

    result = BlockSelfChecker().check(
        block={"block_id": "SEC-001", "content": ""},
        block_spec={"id": "SEC-001", "validation_rules": {"min_length_words": 50}},
    )

    assert result.status == "FAIL"


def test_block_self_check_detects_too_short_and_forbidden():
    from ops.docgen.block_self_check import BlockSelfChecker

    result = BlockSelfChecker().check(
        block={"block_id": "SEC-002", "content": "tbd placeholder text"},
        block_spec={
            "id": "SEC-002",
            "validation_rules": {
                "min_length_words": 50,
                "forbidden_elements": ["tbd"],
            },
        },
    )

    assert result.status == "WARN"
    issue_types = {i["issue_type"] for i in result.issues}
    assert "too_short" in issue_types
    assert "forbidden_element_present" in issue_types
