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
    """Verify load_policy() falls back to hardcoded defaults on missing file."""

    def test_load_policy_falls_back_when_file_missing(self, monkeypatch, tmp_path):
        import ops.docsreg.docsreg_standards_policy as policy_mod

        # Point _POLICY_PATH at a non-existent file
        nonexistent = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr(policy_mod, "_POLICY_PATH", nonexistent)

        # Should not raise — must return valid defaults
        ref_standards, patterns, prefixes = policy_mod.load_policy()

        assert isinstance(ref_standards, frozenset), "fallback ref_standards must be frozenset"
        assert len(ref_standards) > 0, "fallback ref_standards must not be empty"
        assert isinstance(patterns, list), "fallback patterns must be list"
        assert len(patterns) > 0, "fallback patterns must not be empty"
        assert isinstance(prefixes, tuple), "fallback prefixes must be tuple"
        assert len(prefixes) > 0, "fallback prefixes must not be empty"
