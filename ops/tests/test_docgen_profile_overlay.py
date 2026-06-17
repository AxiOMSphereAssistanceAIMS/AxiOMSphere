from ops.docgen.universal_overlay.profile_overlay import (
    build_profile_overlay,
    load_existing_profile,
)


def test_build_profile_overlay_defaults():
    profile = build_profile_overlay("maintenance_procedure")

    assert profile.document_type == "maintenance_procedure"
    assert profile.target_quality == 0.98
    assert profile.quality_weights["coverage"] > 0


def test_build_profile_overlay_uses_existing_profile():
    profile = build_profile_overlay(
        "policy_framework",
        {
            "target_quality": 0.97,
            "required_sections": ["purpose", "governance"],
            "source": "document_type_profiles.py",
        },
    )

    assert profile.target_quality == 0.97
    assert "governance" in profile.required_sections
    assert profile.source == "document_type_profiles.py"


def test_load_existing_profile_from_canonical_module():
    profile = load_existing_profile("technical_report")

    assert profile is not None
    assert profile["document_type"] == "technical_report"
    assert profile["source"] == "document_type_profiles.py"
