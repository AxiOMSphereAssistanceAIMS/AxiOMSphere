"""
Tests for DOCSREG Approved Standards Policy YAML externalisation.

Covers:
  - TestPolicyYamlFile       — verifies the YAML file itself is valid and complete
  - TestModuleLoadedFromYaml — verifies the module loaded the YAML correctly
  - TestPolicyFallback       — verifies graceful fallback when YAML is missing
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLICY_PATH = _PROJECT_ROOT / "config/docsreg/approved_standards_policy.yaml"


# ---------------------------------------------------------------------------
# TestPolicyYamlFile — YAML file structure and content
# ---------------------------------------------------------------------------


class TestPolicyYamlFile:
    """Verify the config/docsreg/approved_standards_policy.yaml file itself."""

    def test_yaml_file_exists(self):
        assert _POLICY_PATH.exists(), (
            f"Policy YAML not found at {_POLICY_PATH}"
        )

    def test_yaml_is_valid(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert data is not None, "YAML parsed to None (empty file?)"

    def test_yaml_has_required_sections(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for key in ("reference_standards", "fabricated_patterns", "iso_prefixes"):
            assert key in data, f"Missing required key '{key}' in policy YAML"

    def test_reference_standards_are_strings(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for entry in data["reference_standards"]:
            assert isinstance(entry, str), (
                f"reference_standards entry is not a string: {entry!r}"
            )

    def test_fabricated_patterns_are_valid_regex(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for pattern in data["fabricated_patterns"]:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                pytest.fail(
                    f"fabricated_patterns entry {pattern!r} is not valid regex: {exc}"
                )

    def test_iso_prefixes_are_strings(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for entry in data["iso_prefixes"]:
            assert isinstance(entry, str), (
                f"iso_prefixes entry is not a string: {entry!r}"
            )

    def test_canonical_iso_standards_present(self):
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        ref_standards = set(data["reference_standards"])
        for expected in ("ISO 55001", "ISO 55002", "ISO 9000"):
            assert expected in ref_standards, (
                f"Expected canonical standard '{expected}' missing from reference_standards"
            )


# ---------------------------------------------------------------------------
# TestModuleLoadedFromYaml — module constants reflect YAML contents
# ---------------------------------------------------------------------------


class TestModuleLoadedFromYaml:
    """Verify the module loaded REFERENCE_STANDARDS etc. from the YAML file."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        from ops.agents.skills import docsreg_reference_governance as mod
        self.mod = mod

    def test_reference_standards_is_frozenset(self):
        assert isinstance(self.mod.REFERENCE_STANDARDS, frozenset)

    def test_fabricated_patterns_is_list(self):
        assert isinstance(self.mod.FABRICATED_STANDARDS_PATTERNS, list)

    def test_iso_prefixes_is_tuple(self):
        assert isinstance(self.mod._ISO_PREFIXES, tuple)

    def test_fabricated_re_is_compiled(self):
        assert isinstance(self.mod._FABRICATED_RE, re.Pattern)

    def test_iso_55001_in_reference_standards(self):
        assert "ISO 55001" in self.mod.REFERENCE_STANDARDS

    def test_api_pattern_matches_api_510(self):
        assert self.mod._FABRICATED_RE.search("API 510") is not None

    def test_nace_pattern_matches_nace_sp0169(self):
        assert self.mod._FABRICATED_RE.search("NACE SP0169") is not None


# ---------------------------------------------------------------------------
# TestPolicyFallback — graceful degradation when YAML is absent
# ---------------------------------------------------------------------------


class TestPolicyFallback:
    """Verify load_policy() falls back to hardcoded defaults on missing/malformed file."""

    def _assert_valid_defaults(
        self,
        ref_standards: object,
        patterns: object,
        prefixes: object,
    ) -> None:
        assert isinstance(ref_standards, frozenset), "fallback ref_standards must be frozenset"
        assert len(ref_standards) > 0, "fallback ref_standards must not be empty"  # type: ignore[arg-type]
        assert isinstance(patterns, list), "fallback patterns must be list"
        assert len(patterns) > 0, "fallback patterns must not be empty"  # type: ignore[arg-type]
        assert isinstance(prefixes, tuple), "fallback prefixes must be tuple"
        assert len(prefixes) > 0, "fallback prefixes must not be empty"  # type: ignore[arg-type]

    def test_load_policy_falls_back_when_file_missing(self, monkeypatch, tmp_path):
        import ops.docsreg.docsreg_standards_policy as policy_mod

        nonexistent = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr(policy_mod, "_POLICY_PATH", nonexistent)

        ref_standards, patterns, prefixes = policy_mod.load_policy()
        self._assert_valid_defaults(ref_standards, patterns, prefixes)

    def test_load_policy_falls_back_on_invalid_yaml(self, monkeypatch, tmp_path):
        import ops.docsreg.docsreg_standards_policy as policy_mod

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(":: this is not valid yaml ::", encoding="utf-8")
        monkeypatch.setattr(policy_mod, "_POLICY_PATH", bad_yaml)

        ref_standards, patterns, prefixes = policy_mod.load_policy()
        self._assert_valid_defaults(ref_standards, patterns, prefixes)

    def test_load_policy_falls_back_on_missing_keys(self, monkeypatch, tmp_path):
        """YAML exists and parses but is missing required sections."""
        import ops.docsreg.docsreg_standards_policy as policy_mod

        partial_yaml = tmp_path / "partial.yaml"
        partial_yaml.write_text(
            "reference_standards:\n  - ISO 9000\n",  # missing fabricated_patterns + iso_prefixes
            encoding="utf-8",
        )
        monkeypatch.setattr(policy_mod, "_POLICY_PATH", partial_yaml)

        ref_standards, patterns, prefixes = policy_mod.load_policy()
        self._assert_valid_defaults(ref_standards, patterns, prefixes)

    def test_load_policy_falls_back_on_empty_file(self, monkeypatch, tmp_path):
        """Empty YAML file (safe_load returns None) must not crash."""
        import ops.docsreg.docsreg_standards_policy as policy_mod

        empty_yaml = tmp_path / "empty.yaml"
        empty_yaml.write_text("", encoding="utf-8")
        monkeypatch.setattr(policy_mod, "_POLICY_PATH", empty_yaml)

        ref_standards, patterns, prefixes = policy_mod.load_policy()
        self._assert_valid_defaults(ref_standards, patterns, prefixes)


# ---------------------------------------------------------------------------
# TestPolicyInvariant — cross-field consistency checks
# ---------------------------------------------------------------------------


class TestPolicyInvariant:
    """Verify invariants that span multiple YAML sections."""

    def test_iso_prefixes_are_subset_of_reference_standards(self):
        """Every iso_prefixes entry must appear in reference_standards.

        These two lists serve different purposes (prefix matching vs. exact match)
        but should stay in sync — an ISO prefix that isn't in reference_standards
        would create a verifiable standard whose prefix isn't recognised.
        """
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        ref_set = set(data["reference_standards"])
        for prefix in data["iso_prefixes"]:
            assert prefix in ref_set, (
                f"iso_prefixes entry '{prefix}' is not in reference_standards — "
                "the two lists must stay in sync"
            )
