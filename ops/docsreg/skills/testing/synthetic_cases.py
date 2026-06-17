"""Synthetic test case generation for PHASE 7 skill testing."""
import hashlib
from datetime import datetime, timedelta
from typing import List

from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillTestInput,
    SkillTestOutput,
    DataRetentionReport,
    DataRetentionStatus,
    SkillTestCase,
    SkillVerdict,
)


def _hash_content(content: str) -> str:
    """SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


class SyntheticCaseGenerator:
    """Generates realistic synthetic test cases for skill validation."""

    @staticmethod
    def generate_all_cases() -> List[SkillTestCase]:
        """Generate all 30 test cases (5 per skill, 6 skills)."""
        all_cases = []

        for skill in SkillName:
            cases = SyntheticCaseGenerator._generate_cases_for_skill(skill)
            all_cases.extend(cases)

        return all_cases

    @staticmethod
    def _generate_cases_for_skill(skill: SkillName) -> List[SkillTestCase]:
        """Generate 5 test cases for a single skill."""
        if skill == SkillName.FIX_TIMEOUT:
            return SyntheticCaseGenerator._cases_fix_timeout()
        elif skill == SkillName.FIX_STRUCTURE:
            return SyntheticCaseGenerator._cases_fix_structure()
        elif skill == SkillName.FIX_POLICY_VIOLATION:
            return SyntheticCaseGenerator._cases_fix_policy_violation()
        elif skill == SkillName.FIX_QUALITY_GATE:
            return SyntheticCaseGenerator._cases_fix_quality_gate()
        elif skill == SkillName.FIX_DATA_LOSS:
            return SyntheticCaseGenerator._cases_fix_data_loss()
        elif skill == SkillName.FIX_RESOURCE_EXHAUSTION:
            return SyntheticCaseGenerator._cases_fix_resource_exhaustion()
        else:
            return []

    @staticmethod
    def _cases_fix_timeout() -> List[SkillTestCase]:
        """FIX_TIMEOUT: Handle retry logic for slow operations."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=1)

        # Case 1: Simple timeout retry (all good)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_001",
            scenario_description="API call timed out on first attempt, succeeded on retry",
            input_content="Document content with incomplete API fetch marker [TIMEOUT_MARKER_0]",
            input_hash=_hash_content("Document content with incomplete API fetch marker [TIMEOUT_MARKER_0]"),
            expected_repair_type="retry_with_timeout_increase",
            archetype_type="technical_report",
        )
        output1 = SkillTestOutput(
            test_case_id="timeout_001",
            repaired_content="Document content with complete API fetch result [API_RESULT_COMPLETE]",
            output_hash=_hash_content("Document content with complete API fetch result [API_RESULT_COMPLETE]"),
            repair_applied=True,
            quality_before=0.72,
            quality_after=0.88,
            quality_delta=0.16,
            repair_time_ms=4200,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.3,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Timeout resolved with retry logic; quality improved 0.72→0.88; no data loss",
        ))

        # Case 2: Timeout with partial content (advisory)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_002",
            scenario_description="Timeout during document section retrieval, partial content recovered",
            input_content="Section 1 complete. Section 2 [TIMEOUT_START] Section 3 complete.",
            input_hash=_hash_content("Section 1 complete. Section 2 [TIMEOUT_START] Section 3 complete."),
            expected_repair_type="retry_with_timeout_increase",
            archetype_type="maintenance_procedure",
        )
        output2 = SkillTestOutput(
            test_case_id="timeout_002",
            repaired_content="Section 1 complete. Section 2 [PARTIAL_RECOVERY]. Section 3 complete.",
            output_hash=_hash_content("Section 1 complete. Section 2 [PARTIAL_RECOVERY]. Section 3 complete."),
            repair_applied=True,
            quality_before=0.65,
            quality_after=0.76,
            quality_delta=0.11,
            repair_time_ms=5100,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.8,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=1),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Timeout recovery successful; quality improved 0.65→0.76; advisory data loss 1.8%",
        ))

        # Case 3: Timeout with critical section loss (blocked)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_003",
            scenario_description="Timeout during critical control section, >2% loss",
            input_content="Header [COMPLETE]. Document Control Section [TIMEOUT]. Footer [COMPLETE].",
            input_hash=_hash_content("Header [COMPLETE]. Document Control Section [TIMEOUT]. Footer [COMPLETE]."),
            expected_repair_type="retry_with_timeout_increase",
            archetype_type="policy_framework",
        )
        output3 = SkillTestOutput(
            test_case_id="timeout_003",
            repaired_content="Header [COMPLETE]. Document Control Section [LOST]. Footer [COMPLETE].",
            output_hash=_hash_content("Header [COMPLETE]. Document Control Section [LOST]. Footer [COMPLETE]."),
            repair_applied=True,
            quality_before=0.80,
            quality_after=0.71,
            quality_delta=-0.09,
            repair_time_ms=6000,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.3,
            sections_lost=["Document Control"],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=2),
            verdict=SkillVerdict.BLOCKED,
            reasoning="Timeout recovery caused critical section loss (2.3%); repair rejected by data retention gate",
        ))

        # Case 4: Multiple retries successful (promoted)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_004",
            scenario_description="Multiple timeout retries with exponential backoff, eventually successful",
            input_content="Content A [TIMEOUT_RETRY_1] Content B [TIMEOUT_RETRY_2] Content C [TIMEOUT_RETRY_3]",
            input_hash=_hash_content("Content A [TIMEOUT_RETRY_1] Content B [TIMEOUT_RETRY_2] Content C [TIMEOUT_RETRY_3]"),
            expected_repair_type="retry_with_timeout_increase",
            archetype_type="technical_report",
        )
        output4 = SkillTestOutput(
            test_case_id="timeout_004",
            repaired_content="Content A [SUCCESS] Content B [SUCCESS] Content C [SUCCESS]",
            output_hash=_hash_content("Content A [SUCCESS] Content B [SUCCESS] Content C [SUCCESS]"),
            repair_applied=True,
            quality_before=0.68,
            quality_after=0.94,
            quality_delta=0.26,
            repair_time_ms=12500,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=3),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Multiple retries succeeded; significant quality improvement 0.68→0.94; no data loss",
        ))

        # Case 5: Timeout with fallback content (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_005",
            scenario_description="Timeout during real-time API fetch, fallback to cached content",
            input_content="Live data fetch [TIMEOUT] cached fallback [AVAILABLE]",
            input_hash=_hash_content("Live data fetch [TIMEOUT] cached fallback [AVAILABLE]"),
            expected_repair_type="retry_with_timeout_increase",
            archetype_type="maintenance_procedure",
        )
        output5 = SkillTestOutput(
            test_case_id="timeout_005",
            repaired_content="Live data fetch [CACHED_BACKUP] cached fallback [USED]",
            output_hash=_hash_content("Live data fetch [CACHED_BACKUP] cached fallback [USED]"),
            repair_applied=True,
            quality_before=0.75,
            quality_after=0.82,
            quality_delta=0.07,
            repair_time_ms=2100,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.5,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_TIMEOUT,
            test_case_id="timeout_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=4),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Fallback cache used successfully; quality improved 0.75→0.82; minimal data loss 0.5%",
        ))

        return cases

    @staticmethod
    def _cases_fix_structure() -> List[SkillTestCase]:
        """FIX_STRUCTURE: Repair malformed document structure."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=2)

        # Case 1: Malformed heading fixed (promoted)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_001",
            scenario_description="LLM-generated heading format corrected to ADNOC standard",
            input_content="== Overview == Some content here",
            input_hash=_hash_content("== Overview == Some content here"),
            expected_repair_type="structural_fix",
            archetype_type="policy_framework",
        )
        output1 = SkillTestOutput(
            test_case_id="structure_001",
            repaired_content="# Overview\n\nSome content here",
            output_hash=_hash_content("# Overview\n\nSome content here"),
            repair_applied=True,
            quality_before=0.70,
            quality_after=0.93,
            quality_delta=0.23,
            repair_time_ms=1200,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.1,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Heading format standardized; validation now passes; quality 0.70→0.93",
        ))

        # Case 2: Missing required section added (promoted)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_002",
            scenario_description="Required 'Scope' section inferred and added",
            input_content="# Overview\nContent here\n# Implementation\nMore content",
            input_hash=_hash_content("# Overview\nContent here\n# Implementation\nMore content"),
            expected_repair_type="structural_fix",
            archetype_type="technical_report",
        )
        output2 = SkillTestOutput(
            test_case_id="structure_002",
            repaired_content="# Overview\nContent here\n# Scope\nInferred scope section\n# Implementation\nMore content",
            output_hash=_hash_content("# Overview\nContent here\n# Scope\nInferred scope section\n# Implementation\nMore content"),
            repair_applied=True,
            quality_before=0.68,
            quality_after=0.85,
            quality_delta=0.17,
            repair_time_ms=2300,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=5),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Missing required section inferred and added; structure now valid; quality improved",
        ))

        # Case 3: Broken table structure (advisory)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_003",
            scenario_description="Markdown table with missing delimiters, partial recovery",
            input_content="| Col1 | Col2\nRow1 | Data1 | Data2",
            input_hash=_hash_content("| Col1 | Col2\nRow1 | Data1 | Data2"),
            expected_repair_type="structural_fix",
            archetype_type="maintenance_procedure",
        )
        output3 = SkillTestOutput(
            test_case_id="structure_003",
            repaired_content="| Col1 | Col2 |\n|-----|-----|\n| Data1 | Data2 |",
            output_hash=_hash_content("| Col1 | Col2 |\n|-----|-----|\n| Data1 | Data2 |"),
            repair_applied=True,
            quality_before=0.62,
            quality_after=0.78,
            quality_delta=0.16,
            repair_time_ms=1800,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.9,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=10),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Table structure repaired; minor row loss 1.9%; quality improved 0.62→0.78",
        ))

        # Case 4: Nested list corruption (blocked)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_004",
            scenario_description="Complex nested list severely corrupted, >2% content loss",
            input_content="- Item 1\n  - Subitem 1a\n  - Subitem 1b [CORRUPT]\n- Item 2 [LOST]\n- Item 3",
            input_hash=_hash_content("- Item 1\n  - Subitem 1a\n  - Subitem 1b [CORRUPT]\n- Item 2 [LOST]\n- Item 3"),
            expected_repair_type="structural_fix",
            archetype_type="policy_framework",
        )
        output4 = SkillTestOutput(
            test_case_id="structure_004",
            repaired_content="- Item 1\n  - Subitem 1a\n- Item 3",
            output_hash=_hash_content("- Item 1\n  - Subitem 1a\n- Item 3"),
            repair_applied=True,
            quality_before=0.55,
            quality_after=0.60,
            quality_delta=0.05,
            repair_time_ms=2500,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.4,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=15),
            verdict=SkillVerdict.BLOCKED,
            reasoning="List structure repair required removal of corrupted items; data loss 2.4% exceeds threshold",
        ))

        # Case 5: Code block indentation (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_005",
            scenario_description="Code block indentation corrected, fence delimiters fixed",
            input_content="```python\ndef hello():\nprint('world')\n```",
            input_hash=_hash_content("```python\ndef hello():\nprint('world')\n```"),
            expected_repair_type="structural_fix",
            archetype_type="technical_report",
        )
        output5 = SkillTestOutput(
            test_case_id="structure_005",
            repaired_content="```python\ndef hello():\n    print('world')\n```",
            output_hash=_hash_content("```python\ndef hello():\n    print('world')\n```"),
            repair_applied=True,
            quality_before=0.81,
            quality_after=0.96,
            quality_delta=0.15,
            repair_time_ms=900,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_STRUCTURE,
            test_case_id="structure_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=20),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Code block formatting corrected; syntax now valid; quality 0.81→0.96",
        ))

        return cases

    @staticmethod
    def _cases_fix_policy_violation() -> List[SkillTestCase]:
        """FIX_POLICY_VIOLATION: Repair archetype policy violations."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=3)

        # Case 1: Missing required field (promoted)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_001",
            scenario_description="Missing 'Document ID' required field, inferred from context",
            input_content="# Technical Report\nAuthor: John Doe\nDate: 2026-06-17\nContent here",
            input_hash=_hash_content("# Technical Report\nAuthor: John Doe\nDate: 2026-06-17\nContent here"),
            expected_repair_type="escalate_to_validation_repair",
            archetype_type="technical_report",
        )
        output1 = SkillTestOutput(
            test_case_id="policy_001",
            repaired_content="# Technical Report\nDocument ID: TR-2026-06-17-001\nAuthor: John Doe\nDate: 2026-06-17\nContent here",
            output_hash=_hash_content("# Technical Report\nDocument ID: TR-2026-06-17-001\nAuthor: John Doe\nDate: 2026-06-17\nContent here"),
            repair_applied=True,
            quality_before=0.74,
            quality_after=0.91,
            quality_delta=0.17,
            repair_time_ms=1500,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Required Document ID field inferred and added; policy now compliant; quality improved",
        ))

        # Case 2: Invalid reference format (promoted)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_002",
            scenario_description="Reference citations use wrong format, corrected to policy standard",
            input_content="See [ref1] for details. Also consult [ref2]. Based on [ref3].",
            input_hash=_hash_content("See [ref1] for details. Also consult [ref2]. Based on [ref3]."),
            expected_repair_type="escalate_to_validation_repair",
            archetype_type="policy_framework",
        )
        output2 = SkillTestOutput(
            test_case_id="policy_002",
            repaired_content="See [ISO-9001-2024] for details. Also consult [ADNOC-STD-001]. Based on [API-Policy-v3].",
            output_hash=_hash_content("See [ISO-9001-2024] for details. Also consult [ADNOC-STD-001]. Based on [API-Policy-v3]."),
            repair_applied=True,
            quality_before=0.69,
            quality_after=0.87,
            quality_delta=0.18,
            repair_time_ms=2000,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.2,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=6),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Reference format standardized; all citations now compliant; quality 0.69→0.87",
        ))

        # Case 3: Expired approval (advisory)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_003",
            scenario_description="Approval timestamp expired, re-approval required but content preserved",
            input_content="# Maintenance Procedure\nApproved: 2024-06-17 (EXPIRED)\nRevision: 2.1\nSteps: 1,2,3,4,5",
            input_hash=_hash_content("# Maintenance Procedure\nApproved: 2024-06-17 (EXPIRED)\nRevision: 2.1\nSteps: 1,2,3,4,5"),
            expected_repair_type="escalate_to_validation_repair",
            archetype_type="maintenance_procedure",
        )
        output3 = SkillTestOutput(
            test_case_id="policy_003",
            repaired_content="# Maintenance Procedure\nApproved: 2026-06-17 (RENEWED)\nRevision: 2.2\nSteps: 1,2,3,4,5",
            output_hash=_hash_content("# Maintenance Procedure\nApproved: 2026-06-17 (RENEWED)\nRevision: 2.2\nSteps: 1,2,3,4,5"),
            repair_applied=True,
            quality_before=0.76,
            quality_after=0.83,
            quality_delta=0.07,
            repair_time_ms=1100,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.7,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=12),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Approval renewed; revision updated; minor formatting loss 1.7%; compliant but advisory",
        ))

        # Case 4: Classification mismatch (blocked)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_004",
            scenario_description="Document archetype mismatch, content lost during conversion attempt",
            input_content="[Type: technical_report] [Content for tech reporting] [API Usage Guide] [Code Examples]",
            input_hash=_hash_content("[Type: technical_report] [Content for tech reporting] [API Usage Guide] [Code Examples]"),
            expected_repair_type="escalate_to_validation_repair",
            archetype_type="technical_report",
        )
        output4 = SkillTestOutput(
            test_case_id="policy_004",
            repaired_content="[Type: policy_framework] [Content for policy] [API Usage Guide]",
            output_hash=_hash_content("[Type: policy_framework] [Content for policy] [API Usage Guide]"),
            repair_applied=True,
            quality_before=0.72,
            quality_after=0.64,
            quality_delta=-0.08,
            repair_time_ms=2800,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.2,
            sections_lost=["Code Examples"],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=18),
            verdict=SkillVerdict.BLOCKED,
            reasoning="Archetype conversion caused section loss (2.2%); incompatible archetype; repair rejected",
        ))

        # Case 5: Metadata correction (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_005",
            scenario_description="Metadata fields corrected: version, status, revision",
            input_content="Title: Policy\nVersion: unknown\nStatus: draft\nRevision: 0",
            input_hash=_hash_content("Title: Policy\nVersion: unknown\nStatus: draft\nRevision: 0"),
            expected_repair_type="escalate_to_validation_repair",
            archetype_type="policy_framework",
        )
        output5 = SkillTestOutput(
            test_case_id="policy_005",
            repaired_content="Title: Policy\nVersion: 3.2.1\nStatus: approved\nRevision: 12",
            output_hash=_hash_content("Title: Policy\nVersion: 3.2.1\nStatus: approved\nRevision: 12"),
            repair_applied=True,
            quality_before=0.77,
            quality_after=0.92,
            quality_delta=0.15,
            repair_time_ms=1300,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_POLICY_VIOLATION,
            test_case_id="policy_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=24),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Metadata standardized; version and status now compliant; quality improved significantly",
        ))

        return cases

    @staticmethod
    def _cases_fix_quality_gate() -> List[SkillTestCase]:
        """FIX_QUALITY_GATE: Improve document quality score."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=4)

        # Case 1: Clarity enhancement (promoted)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_001",
            scenario_description="Vague language clarified, examples added",
            input_content="The system works well. It processes data. Results are good.",
            input_hash=_hash_content("The system works well. It processes data. Results are good."),
            expected_repair_type="quality_enhancement",
            archetype_type="technical_report",
        )
        output1 = SkillTestOutput(
            test_case_id="quality_001",
            repaired_content="The system achieves 99.2% uptime. It processes 10,000 requests/second. Results exceed 95% accuracy targets.",
            output_hash=_hash_content("The system achieves 99.2% uptime. It processes 10,000 requests/second. Results exceed 95% accuracy targets."),
            repair_applied=True,
            quality_before=0.58,
            quality_after=0.89,
            quality_delta=0.31,
            repair_time_ms=3200,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Clarity significantly improved with concrete metrics; quality 0.58→0.89; no data loss",
        ))

        # Case 2: Structure optimization (promoted)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_002",
            scenario_description="Content reorganized into logical sections with transitions",
            input_content="Background. First step. Second step. Background details. Third step. Conclusion.",
            input_hash=_hash_content("Background. First step. Second step. Background details. Third step. Conclusion."),
            expected_repair_type="quality_enhancement",
            archetype_type="maintenance_procedure",
        )
        output2 = SkillTestOutput(
            test_case_id="quality_002",
            repaired_content="## Background\nBackground. Background details.\n\n## Procedure\n1. First step.\n2. Second step.\n3. Third step.\n\n## Conclusion\nConclusion.",
            output_hash=_hash_content("## Background\nBackground. Background details.\n\n## Procedure\n1. First step.\n2. Second step.\n3. Third step.\n\n## Conclusion\nConclusion."),
            repair_applied=True,
            quality_before=0.65,
            quality_after=0.84,
            quality_delta=0.19,
            repair_time_ms=2100,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.1,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=8),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Structure optimized with logical sections; readability improved; quality 0.65→0.84",
        ))

        # Case 3: Partial enhancement (advisory)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_003",
            scenario_description="Grammar corrected but content specificity partially lost",
            input_content="The procedures is complex. Many things must be did. Results varies.",
            input_hash=_hash_content("The procedures is complex. Many things must be did. Results varies."),
            expected_repair_type="quality_enhancement",
            archetype_type="policy_framework",
        )
        output3 = SkillTestOutput(
            test_case_id="quality_003",
            repaired_content="The procedures are complex. Several steps must be completed. Results are variable.",
            output_hash=_hash_content("The procedures are complex. Several steps must be completed. Results are variable."),
            repair_applied=True,
            quality_before=0.52,
            quality_after=0.71,
            quality_delta=0.19,
            repair_time_ms=1600,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.6,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=14),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Grammar corrected and clarity improved; quality 0.52→0.71; advisory loss 1.6% on specificity",
        ))

        # Case 4: Simplification causing loss (blocked)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_004",
            scenario_description="Oversimplification attempt removes critical technical details (>2% loss)",
            input_content="Parameter A (0-100 range, default 50): sets threshold. Parameter B (0-50): sets tolerance. Parameter C: debug flag.",
            input_hash=_hash_content("Parameter A (0-100 range, default 50): sets threshold. Parameter B (0-50): sets tolerance. Parameter C: debug flag."),
            expected_repair_type="quality_enhancement",
            archetype_type="technical_report",
        )
        output4 = SkillTestOutput(
            test_case_id="quality_004",
            repaired_content="Parameter A: threshold control. Parameter B: tolerance. Parameters simplified.",
            output_hash=_hash_content("Parameter A: threshold control. Parameter B: tolerance. Parameters simplified."),
            repair_applied=True,
            quality_before=0.73,
            quality_after=0.65,
            quality_delta=-0.08,
            repair_time_ms=1900,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.5,
            sections_lost=[],
            fields_lost=["Parameter ranges", "Default values"],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=20),
            verdict=SkillVerdict.BLOCKED,
            reasoning="Oversimplification lost critical parameter specifications (2.5%); quality degraded; repair rejected",
        ))

        # Case 5: Comprehensive enhancement (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_005",
            scenario_description="Complete content enhancement with examples, diagrams reference, and metrics",
            input_content="System overview. Architecture exists. Performance is good.",
            input_hash=_hash_content("System overview. Architecture exists. Performance is good."),
            expected_repair_type="quality_enhancement",
            archetype_type="technical_report",
        )
        output5 = SkillTestOutput(
            test_case_id="quality_005",
            repaired_content="System overview: Enterprise-grade asset management platform. Architecture: Microservices on Kubernetes. Performance: 99.95% availability, <100ms latency. [See Figure 3.2 for diagram]",
            output_hash=_hash_content("System overview: Enterprise-grade asset management platform. Architecture: Microservices on Kubernetes. Performance: 99.95% availability, <100ms latency. [See Figure 3.2 for diagram]"),
            repair_applied=True,
            quality_before=0.61,
            quality_after=0.91,
            quality_delta=0.30,
            repair_time_ms=3800,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_QUALITY_GATE,
            test_case_id="quality_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=26),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Comprehensive enhancement with specific metrics and references; quality 0.61→0.91; no loss",
        ))

        return cases

    @staticmethod
    def _cases_fix_data_loss() -> List[SkillTestCase]:
        """FIX_DATA_LOSS: Handle data loss during repairs."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=5)

        # Case 1: Minimal loss recovery (promoted)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_001",
            scenario_description="Corrupted section, minimal content loss (<1%)",
            input_content="Section A [COMPLETE]. Section B [PARTIAL_CORRUPT XXXXX]. Section C [COMPLETE].",
            input_hash=_hash_content("Section A [COMPLETE]. Section B [PARTIAL_CORRUPT XXXXX]. Section C [COMPLETE]."),
            expected_repair_type="data_recovery",
            archetype_type="maintenance_procedure",
        )
        output1 = SkillTestOutput(
            test_case_id="dataloss_001",
            repaired_content="Section A [COMPLETE]. Section B [RECOVERED]. Section C [COMPLETE].",
            output_hash=_hash_content("Section A [COMPLETE]. Section B [RECOVERED]. Section C [COMPLETE]."),
            repair_applied=True,
            quality_before=0.67,
            quality_after=0.84,
            quality_delta=0.17,
            repair_time_ms=2400,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.8,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Data loss minimal (0.8%); section recovered successfully; quality improved 0.67→0.84",
        ))

        # Case 2: Backup restoration (promoted)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_002",
            scenario_description="Lost content recovered from backup, verified against hash",
            input_content="Header [OK]. Content [MISSING - CHECK_BACKUP_0xA1F2]. Footer [OK].",
            input_hash=_hash_content("Header [OK]. Content [MISSING - CHECK_BACKUP_0xA1F2]. Footer [OK]."),
            expected_repair_type="data_recovery",
            archetype_type="technical_report",
        )
        output2 = SkillTestOutput(
            test_case_id="dataloss_002",
            repaired_content="Header [OK]. Content [RESTORED_FROM_BACKUP_0xA1F2]. Footer [OK].",
            output_hash=_hash_content("Header [OK]. Content [RESTORED_FROM_BACKUP_0xA1F2]. Footer [OK]."),
            repair_applied=True,
            quality_before=0.70,
            quality_after=0.95,
            quality_delta=0.25,
            repair_time_ms=1800,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.0,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=7),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Backup restoration verified; no data loss; quality improved significantly 0.70→0.95",
        ))

        # Case 3: Partial data loss with recovery (advisory)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_003",
            scenario_description="Partial table data recoverable, some rows unrecoverable",
            input_content="| Header1 | Header2 |\n| Row1A | [LOST] |\n| [LOST] | Row2B |\n| Row3A | Row3B |",
            input_hash=_hash_content("| Header1 | Header2 |\n| Row1A | [LOST] |\n| [LOST] | Row2B |\n| Row3A | Row3B |"),
            expected_repair_type="data_recovery",
            archetype_type="policy_framework",
        )
        output3 = SkillTestOutput(
            test_case_id="dataloss_003",
            repaired_content="| Header1 | Header2 |\n| Row1A | [RECOVERED] |\n| Row3A | Row3B |",
            output_hash=_hash_content("| Header1 | Header2 |\n| Row1A | [RECOVERED] |\n| Row3A | Row3B |"),
            repair_applied=True,
            quality_before=0.62,
            quality_after=0.76,
            quality_delta=0.14,
            repair_time_ms=2000,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.9,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=13),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Partial recovery achieved; loss 1.9% (advisory boundary); quality improved but data unavailable",
        ))

        # Case 4: Unrecoverable loss (blocked)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_004",
            scenario_description="Critical section permanently lost, recovery impossible (>2%)",
            input_content="# Document\n## Critical Controls [PERMANENTLY_CORRUPTED]\n## Appendix [OK]",
            input_hash=_hash_content("# Document\n## Critical Controls [PERMANENTLY_CORRUPTED]\n## Appendix [OK]"),
            expected_repair_type="data_recovery",
            archetype_type="maintenance_procedure",
        )
        output4 = SkillTestOutput(
            test_case_id="dataloss_004",
            repaired_content="# Document\n## Appendix [OK]",
            output_hash=_hash_content("# Document\n## Appendix [OK]"),
            repair_applied=True,
            quality_before=0.80,
            quality_after=0.52,
            quality_delta=-0.28,
            repair_time_ms=1500,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.8,
            sections_lost=["Critical Controls"],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=19),
            verdict=SkillVerdict.BLOCKED,
            reasoning="Critical section unrecoverable; loss 2.8% exceeds threshold; repair would degrade quality",
        ))

        # Case 5: Intelligent data reconstruction (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_005",
            scenario_description="Lost metadata reconstructed from contextual clues and linked data",
            input_content="Document [TITLE_LOST]. Date: 2026-06-17. Author [NAME_LOST]. References: 5 items.",
            input_hash=_hash_content("Document [TITLE_LOST]. Date: 2026-06-17. Author [NAME_LOST]. References: 5 items."),
            expected_repair_type="data_recovery",
            archetype_type="technical_report",
        )
        output5 = SkillTestOutput(
            test_case_id="dataloss_005",
            repaired_content="Document: Technical Report on Asset Management. Date: 2026-06-17. Author: System Engineer. References: 5 items [ISO-9001, ADNOC-STD, API-v3, ECC-Framework, AIMS-Policy].",
            output_hash=_hash_content("Document: Technical Report on Asset Management. Date: 2026-06-17. Author: System Engineer. References: 5 items [ISO-9001, ADNOC-STD, API-v3, ECC-Framework, AIMS-Policy]."),
            repair_applied=True,
            quality_before=0.58,
            quality_after=0.86,
            quality_delta=0.28,
            repair_time_ms=3100,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.2,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_DATA_LOSS,
            test_case_id="dataloss_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=25),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Metadata intelligently reconstructed from context; quality improved 0.58→0.86; minimal loss 0.2%",
        ))

        return cases

    @staticmethod
    def _cases_fix_resource_exhaustion() -> List[SkillTestCase]:
        """FIX_RESOURCE_EXHAUSTION: Handle resource constraint repairs."""
        cases = []
        base_time = datetime.utcnow() - timedelta(hours=6)

        # Case 1: Token limit optimization (promoted)
        input1 = SkillTestInput(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_001",
            scenario_description="Document optimized to fit within token limits without quality loss",
            input_content="Very long repetitive documentation with multiple examples " * 200,
            input_hash=_hash_content("Very long repetitive documentation with multiple examples " * 200),
            expected_repair_type="resource_optimization",
            archetype_type="technical_report",
        )
        output1 = SkillTestOutput(
            test_case_id="resource_001",
            repaired_content="Concise documentation summary with key examples and metrics provided.",
            output_hash=_hash_content("Concise documentation summary with key examples and metrics provided."),
            repair_applied=True,
            quality_before=0.72,
            quality_after=0.88,
            quality_delta=0.16,
            repair_time_ms=4500,
        )
        retention1 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.9,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_001",
            scenario_description=input1.scenario_description,
            test_input=input1,
            test_output=output1,
            retention_report=retention1,
            executed_at=base_time,
            verdict=SkillVerdict.PROMOTED,
            reasoning="Token-optimized version improved clarity; quality 0.72→0.88; minimal loss 0.9%",
        ))

        # Case 2: Memory-efficient restructuring (promoted)
        input2 = SkillTestInput(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_002",
            scenario_description="Complex nested structure flattened for memory efficiency",
            input_content="Deeply nested JSON structure with 15 levels of hierarchy and 500KB size.",
            input_hash=_hash_content("Deeply nested JSON structure with 15 levels of hierarchy and 500KB size."),
            expected_repair_type="resource_optimization",
            archetype_type="policy_framework",
        )
        output2 = SkillTestOutput(
            test_case_id="resource_002",
            repaired_content="Flattened JSON structure with 2 levels of hierarchy and 45KB size.",
            output_hash=_hash_content("Flattened JSON structure with 2 levels of hierarchy and 45KB size."),
            repair_applied=True,
            quality_before=0.75,
            quality_after=0.84,
            quality_delta=0.09,
            repair_time_ms=3200,
        )
        retention2 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.3,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_002",
            scenario_description=input2.scenario_description,
            test_input=input2,
            test_output=output2,
            retention_report=retention2,
            executed_at=base_time + timedelta(minutes=9),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Memory optimization successful; quality improved 0.75→0.84; negligible loss 0.3%",
        ))

        # Case 3: GPU memory pressure handling (advisory)
        input3 = SkillTestInput(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_003",
            scenario_description="Large batch split into smaller chunks, some processing overhead",
            input_content="Large batch processing 10,000 items in single pass exceeding VRAM.",
            input_hash=_hash_content("Large batch processing 10,000 items in single pass exceeding VRAM."),
            expected_repair_type="resource_optimization",
            archetype_type="maintenance_procedure",
        )
        output3 = SkillTestOutput(
            test_case_id="resource_003",
            repaired_content="Batch split: 2,500 items × 4 passes, VRAM within limits.",
            output_hash=_hash_content("Batch split: 2,500 items × 4 passes, VRAM within limits."),
            repair_applied=True,
            quality_before=0.70,
            quality_after=0.77,
            quality_delta=0.07,
            repair_time_ms=5800,
        )
        retention3 = DataRetentionReport(
            status=DataRetentionStatus.ADVISORY,
            token_loss_percentage=1.7,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_003",
            scenario_description=input3.scenario_description,
            test_input=input3,
            test_output=output3,
            retention_report=retention3,
            executed_at=base_time + timedelta(minutes=15),
            verdict=SkillVerdict.ADVISORY,
            reasoning="Resource constraint handled via batching; quality improved 0.70→0.77; advisory loss 1.7%",
        ))

        # Case 4: Aggressive pruning (blocked)
        input4 = SkillTestInput(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_004",
            scenario_description="Aggressive content pruning to fit resource constraints, >2% loss",
            input_content="[SECTION_A: 30%] [SECTION_B: 30%] [SECTION_C: 20%] [APPENDIX: 20%] [REFERENCES: Required]",
            input_hash=_hash_content("[SECTION_A: 30%] [SECTION_B: 30%] [SECTION_C: 20%] [APPENDIX: 20%] [REFERENCES: Required]"),
            expected_repair_type="resource_optimization",
            archetype_type="technical_report",
        )
        output4 = SkillTestOutput(
            test_case_id="resource_004",
            repaired_content="[SECTION_A: 30%] [SECTION_B: 30%] [APPENDIX: Removed] [REFERENCES: Removed]",
            output_hash=_hash_content("[SECTION_A: 30%] [SECTION_B: 30%] [APPENDIX: Removed] [REFERENCES: Removed]"),
            repair_applied=True,
            quality_before=0.82,
            quality_after=0.64,
            quality_delta=-0.18,
            repair_time_ms=2700,
        )
        retention4 = DataRetentionReport(
            status=DataRetentionStatus.FAIL,
            token_loss_percentage=2.6,
            sections_lost=["APPENDIX"],
            fields_lost=[],
            references_lost=["10 items"],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_004",
            scenario_description=input4.scenario_description,
            test_input=input4,
            test_output=output4,
            retention_report=retention4,
            executed_at=base_time + timedelta(minutes=21),
            verdict=SkillVerdict.BLOCKED,
            reasoning="Aggressive pruning lost appendix and references (2.6%); quality degraded; repair rejected",
        ))

        # Case 5: Compression with selective detail (promoted)
        input5 = SkillTestInput(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_005",
            scenario_description="Content compressed while preserving critical details via summarization",
            input_content="Detailed explanation of 50 parameters. For each: description, range, default, constraints, examples.",
            input_hash=_hash_content("Detailed explanation of 50 parameters. For each: description, range, default, constraints, examples."),
            expected_repair_type="resource_optimization",
            archetype_type="policy_framework",
        )
        output5 = SkillTestOutput(
            test_case_id="resource_005",
            repaired_content="Parameter summary table [Name | Type | Default | Constraints]. Critical parameters detailed separately.",
            output_hash=_hash_content("Parameter summary table [Name | Type | Default | Constraints]. Critical parameters detailed separately."),
            repair_applied=True,
            quality_before=0.73,
            quality_after=0.89,
            quality_delta=0.16,
            repair_time_ms=3900,
        )
        retention5 = DataRetentionReport(
            status=DataRetentionStatus.PASS,
            token_loss_percentage=0.6,
            sections_lost=[],
            fields_lost=[],
            references_lost=[],
        )
        cases.append(SkillTestCase(
            skill_name=SkillName.FIX_RESOURCE_EXHAUSTION,
            test_case_id="resource_005",
            scenario_description=input5.scenario_description,
            test_input=input5,
            test_output=output5,
            retention_report=retention5,
            executed_at=base_time + timedelta(minutes=27),
            verdict=SkillVerdict.PROMOTED,
            reasoning="Compression via summarization; critical details preserved; quality 0.73→0.89; minimal loss 0.6%",
        ))

        return cases
