from ops.docgen.universal_overlay.failure_overlay import (
    classify_universal_failure,
    is_critical_universal_failure,
    normalize_issue_to_failure,
)


def test_classify_universal_failure():
    assert classify_universal_failure("fabricated_reference") == "STANDARDS"
    assert classify_universal_failure("missing_required_element") == "COVERAGE"
    assert classify_universal_failure("x") == "UNKNOWN"


def test_critical_failure():
    assert is_critical_universal_failure("fabricated_reference")
    assert not is_critical_universal_failure("section_too_short")


def test_normalize_issue_to_failure():
    assert normalize_issue_to_failure({"issue_type": "missing_required_section"}) == "missing_required_section"
