"""Structural validator for archetype policy enforcement in PHASE 3."""
import re
from typing import Any, Dict, List, Optional, Tuple

from ops.docsreg.archetype_policy_adapter.base import (
    ArchetypeDefinition,
    ConstraintType,
    StructuralViolation,
    ViolationSeverity,
)
from ops.docsreg.archetype_policy_adapter.registry import (
    ConcreteArchetypeRegistry,
    UnknownArchetypeError,
)


class DocumentValidator:
    """Validates documents against archetype policies."""

    def __init__(self):
        """Initialize validator with archetype registry."""
        self.registry = ConcreteArchetypeRegistry()

    def _normalize_section_name(self, name: str) -> str:
        """Normalize section name: strip, lowercase, replace spaces/dashes with underscores."""
        return name.strip().lower().replace(" ", "_").replace("-", "_")

    def _extract_sections(self, content: str) -> Tuple[List[str], Dict[str, str]]:
        """Extract sections from markdown-style headers.

        Returns:
            (list of section names, dict mapping section_name to content)
        """
        # Match markdown headers (#, ##, ###, etc.)
        header_pattern = r"^#+\s+(.+)$"
        lines = content.split("\n")

        sections = []
        section_contents = {}
        current_section = None
        current_content = []

        for line in lines:
            match = re.match(header_pattern, line, re.MULTILINE)
            if match:
                # Save previous section
                if current_section is not None:
                    section_contents[current_section] = "\n".join(current_content).strip()

                # Start new section
                header_text = match.group(1).strip()
                current_section = self._normalize_section_name(header_text)
                sections.append(current_section)
                current_content = []
            else:
                if current_section is not None:
                    current_content.append(line)

        # Save last section
        if current_section is not None:
            section_contents[current_section] = "\n".join(current_content).strip()

        return sections, section_contents

    def _extract_fields(
        self, content: str, required_field_names: List[str]
    ) -> Dict[str, Optional[str]]:
        """Extract field values from document content.

        Detects fields by:
        1. Exact name match (field_name: value)
        2. Spaced variant (field name: value)
        3. Dashed variant (field-name: value)
        """
        fields = {}

        for field_name in required_field_names:
            # Try exact match
            patterns = [
                f"{field_name}:\\s*(.+?)(?:\\n|$)",
                f"{field_name.replace('_', ' ')}:\\s*(.+?)(?:\\n|$)",
                f"{field_name.replace('_', '-')}:\\s*(.+?)(?:\\n|$)",
            ]

            value = None
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    break

            fields[field_name] = value

        return fields

    def _extract_references(self, content: str) -> List[str]:
        """Extract reference identifiers from content."""
        # Match reference patterns like REF_001, ISO-55001, etc.
        ref_pattern = r"\b[A-Z]+[_\-]?\d{3,}\b|\b[A-Z]{2}[_\-]\d{5}\b"
        references = list(set(re.findall(ref_pattern, content)))
        return references

    def _extract_tables(self, content: str) -> List[str]:
        """Extract table identifiers from content."""
        # Match table patterns (| ... | format or table labels)
        table_pattern = r"table\s+(\w+)|(\w+\s+table)|(\|\s*\w+(?:\s+\w+)*\s*\|)"
        matches = re.findall(table_pattern, content, re.IGNORECASE)
        tables = [m[0] or m[1] or m[2] for m in matches if any(m)]
        # Clean up
        tables = [
            t.strip() for t in tables if t and t not in ("", "|") and len(t) > 1
        ]
        return list(set(tables))

    def _extract_semantic_claims(
        self, content: str, patterns: List[str]
    ) -> List[str]:
        """Extract semantic claims matching specified patterns."""
        claims = []
        for pattern in patterns:
            # Find sentences/phrases containing the pattern
            regex = f"\\b{pattern}\\w*\\b"
            matches = re.findall(regex, content, re.IGNORECASE)
            claims.extend(matches)
        return list(set([c.lower() for c in claims]))

    async def validate(
        self, content: str, archetype_name: str, document_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate document against archetype.

        Args:
            content: Document content
            archetype_name: Name of archetype to validate against
            document_id: Optional document identifier

        Returns:
            Validation result dict with keys:
            - valid: bool
            - blocked: bool (hard_gate violations)
            - errors: list of error messages
            - missing_sections: list
            - policy_violations: list of StructuralViolation
            - violations: list of StructuralViolation
            - severity_summary: dict with counts
            - archetype: ArchetypeDefinition or None
            - document_id: str or None
        """
        result = {
            "valid": False,
            "blocked": False,
            "errors": [],
            "missing_sections": [],
            "policy_violations": [],
            "violations": [],
            "severity_summary": {},
            "archetype": None,
            "document_id": document_id,
        }

        # Check if archetype exists
        try:
            archetype = self.registry.get_archetype(archetype_name)
        except UnknownArchetypeError as e:
            # Unknown archetype is a CRITICAL hard-gate blocking violation
            violation = StructuralViolation(
                constraint_id="UNKNOWN_ARCHETYPE_001",
                constraint_type=ConstraintType.METADATA_COMPLETENESS,
                target="archetype",
                severity=ViolationSeverity.CRITICAL,
                message=f"Archetype '{archetype_name}' is not registered. Cannot proceed with validation.",
                actual_value=archetype_name,
                expected_value="known archetype",
                failure_class="UNKNOWN_ARCHETYPE",
                remediation_hint=f"Register archetype or use known archetype. Available: {', '.join(self.registry.list_archetypes())}",
            )
            result["violations"].append(violation)
            result["policy_violations"].append(violation)
            result["blocked"] = True
            result["errors"].append(str(e))
            result["severity_summary"]["CRITICAL"] = 1
            return result

        result["archetype"] = archetype

        # Extract document structure
        sections, section_contents = self._extract_sections(content)
        fields = self._extract_fields(content, archetype.required_fields)
        references = self._extract_references(content)
        tables = self._extract_tables(content)
        semantic_claims = self._extract_semantic_claims(
            content, archetype.semantic_claim_patterns
        )

        # Check required sections
        normalized_required_sections = [
            self._normalize_section_name(s) for s in archetype.required_sections
        ]
        for required_section in normalized_required_sections:
            if required_section not in sections:
                result["missing_sections"].append(required_section)
                violation = StructuralViolation(
                    constraint_id=f"SECTION_{required_section.upper()}_001",
                    constraint_type=ConstraintType.SECTION_REQUIRED,
                    target=required_section,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Required section '{required_section}' is missing",
                    expected_value=required_section,
                    failure_class="MISSING_SECTION",
                    remediation_hint=f"Add section '{required_section}' with appropriate content",
                )
                result["violations"].append(violation)

        # Check required fields
        for field_name in archetype.required_fields:
            if fields.get(field_name) is None:
                violation = StructuralViolation(
                    constraint_id=f"FIELD_{field_name.upper()}_001",
                    constraint_type=ConstraintType.FIELD_REQUIRED,
                    target=field_name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Required field '{field_name}' is missing or empty",
                    field_name=field_name,
                    failure_class="MISSING_FIELD",
                    remediation_hint=f"Add field '{field_name}' with a non-empty value",
                )
                result["violations"].append(violation)

        # Check required references
        for required_ref in archetype.required_references:
            found = any(
                required_ref.lower() in ref.lower() for ref in references
            )
            if not found:
                violation = StructuralViolation(
                    constraint_id=f"REF_{required_ref.upper()}_001",
                    constraint_type=ConstraintType.REFERENCE_REQUIRED,
                    target=required_ref,
                    severity=ViolationSeverity.HIGH,
                    message=f"Required reference '{required_ref}' not found in document",
                    expected_value=required_ref,
                    actual_value=", ".join(references) if references else "none",
                    failure_class="MISSING_REFERENCE",
                    remediation_hint=f"Add reference to '{required_ref}' in the document",
                )
                result["violations"].append(violation)

        # Check required tables
        for required_table in archetype.required_tables:
            found = any(
                required_table.lower() in table.lower() for table in tables
            )
            if not found:
                violation = StructuralViolation(
                    constraint_id=f"TABLE_{required_table.upper()}_001",
                    constraint_type=ConstraintType.TABLE_REQUIRED,
                    target=required_table,
                    severity=ViolationSeverity.HIGH,
                    message=f"Required table '{required_table}' not found in document",
                    expected_value=required_table,
                    failure_class="MISSING_TABLE",
                    remediation_hint=f"Add table '{required_table}' with appropriate data",
                )
                result["violations"].append(violation)

        # Evaluate policy constraints
        for constraint in archetype.constraints:
            if constraint.constraint_type == ConstraintType.SECTION_MIN_LENGTH:
                section_name = constraint.target
                if section_name in section_contents:
                    content_length = len(section_contents[section_name])
                    min_length = constraint.params.get("min_length", 0)
                    if content_length < min_length:
                        violation = StructuralViolation(
                            constraint_id=constraint.constraint_id,
                            constraint_type=constraint.constraint_type,
                            target=constraint.target,
                            severity=constraint.severity,
                            message=f"Section '{section_name}' is too short ({content_length} chars < {min_length} required)",
                            actual_value=content_length,
                            expected_value=min_length,
                            section_name=section_name,
                            failure_class="SECTION_TOO_SHORT",
                            remediation_hint=constraint.remediation_hint,
                            skill_category=constraint.skill_category,
                        )
                        result["violations"].append(violation)

        # Classify violations by severity for summary
        severity_counts = {}
        for violation in result["violations"]:
            severity_str = violation.severity.value
            severity_counts[severity_str] = severity_counts.get(severity_str, 0) + 1

        result["severity_summary"] = severity_counts

        # Determine overall validity and blocking
        critical_violations = [
            v
            for v in result["violations"]
            if v.severity == ViolationSeverity.CRITICAL
        ]
        result["blocked"] = len(critical_violations) > 0
        result["valid"] = len(result["violations"]) == 0
        result["policy_violations"] = result["violations"]

        return result
