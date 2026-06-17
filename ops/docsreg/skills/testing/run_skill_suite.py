"""PHASE 7 Skill Testing Suite Runner — Main entry point for executing and reporting test results.

Orchestrates:
1. Test case loading (30 synthetic cases across 6 skills)
2. Skill execution and verdict assignment
3. Result aggregation and analysis
4. Evidence package generation
5. Deployment readiness assessment
6. JSON and text report export
"""
import sys
from pathlib import Path

from ops.docsreg.skills.testing.framework import SkillTestingFramework
from ops.docsreg.skills.testing.result_aggregator import ResultAggregator
from ops.docsreg.skills.testing.evidence_generator import EvidenceGenerator


def run_skill_suite(output_dir: str = "ops/docsreg/skills/testing/reports") -> dict:
    """Execute complete skill testing suite.

    Args:
        output_dir: Directory to write JSON and text reports

    Returns:
        Dict with execution summary and overall verdict
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Phase 1: Load and execute tests
    print("=" * 100)
    print("PHASE 7 SKILL TESTING FRAMEWORK — EXECUTION")
    print("=" * 100)
    print()

    framework = SkillTestingFramework()
    print("Loading 30 synthetic test cases (5 per skill × 6 skills)...")
    framework.load_test_cases()
    print(f"✓ Loaded {len(framework.test_cases)} test cases")
    print()

    print("Executing all 6 skill suites...")
    framework.execute_all_skills()
    print(f"✓ Executed {len(framework.skill_results)} skill suites")
    print()

    # Phase 2: Aggregate results
    print("Aggregating results...")
    aggregator = ResultAggregator(framework.skill_results)
    summary = aggregator.get_summary()
    print(f"✓ Aggregation complete")
    print()

    # Phase 3: Generate evidence
    print("Generating evidence package...")
    evidence_gen = EvidenceGenerator(framework.skill_results)
    print(f"✓ Evidence generation complete")
    print()

    # Phase 4: Print summary report
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print()
    print(f"Total Skills:        {summary.total_skills}")
    print(f"  PROMOTED:          {summary.promoted_skills}")
    print(f"  ADVISORY:          {summary.advisory_skills}")
    print(f"  BLOCKED:           {summary.blocked_skills}")
    print()
    print(f"Total Test Cases:    {summary.total_test_cases}")
    print(f"  PROMOTED:          {summary.promoted_cases}")
    print(f"  ADVISORY:          {summary.advisory_cases}")
    print(f"  BLOCKED:           {summary.blocked_cases}")
    print()
    print(f"Retention Failures:  {summary.retention_failure_count}")
    print(f"Quality Improvement: {summary.average_quality_improvement:.4f}")
    print(f"Repair Time:         {summary.average_repair_time_ms} ms")
    print()
    print(f"RECOMMENDATION:      {summary.recommendation}")
    print()

    # Phase 5: Print detailed analysis
    print("=" * 100)
    print("DETAILED SKILL CLASSIFICATION")
    print("=" * 100)
    print()
    print(aggregator.generate_report())
    print()

    # Phase 6: Export evidence
    json_report_path = output_path / "evidence_package.json"
    text_report_path = output_path / "evidence_report.txt"

    print("=" * 100)
    print("EXPORTING EVIDENCE")
    print("=" * 100)
    print()

    evidence_gen.export_json(str(json_report_path))
    print(f"✓ JSON evidence exported: {json_report_path}")

    evidence_gen.export_text_report(str(text_report_path))
    print(f"✓ Text report exported: {text_report_path}")
    print()

    # Phase 7: Determine overall verdict for deployment gating
    overall_metrics = framework.get_overall_metrics()

    if overall_metrics.overall_verdict.value == "BLOCKED":
        deployment_status = "BLOCKED_FOR_DEPLOYMENT"
        exit_code = 1
    elif overall_metrics.overall_verdict.value == "ADVISORY":
        deployment_status = "ADVISORY_DEPLOYMENT"
        exit_code = 0
    else:
        deployment_status = "PROMOTED_FOR_DEPLOYMENT"
        exit_code = 0

    print("=" * 100)
    print("DEPLOYMENT READINESS")
    print("=" * 100)
    print()
    print(f"Status: {deployment_status}")
    print(f"Blocked Skills: {summary.blocked_skills}")
    print(f"Advisory Skills: {summary.advisory_skills}")
    print()

    result = {
        "overall_verdict": overall_metrics.overall_verdict.value,
        "deployment_status": deployment_status,
        "total_skills": summary.total_skills,
        "promoted_skills": summary.promoted_skills,
        "advisory_skills": summary.advisory_skills,
        "blocked_skills": summary.blocked_skills,
        "total_test_cases": summary.total_test_cases,
        "promoted_cases": summary.promoted_cases,
        "advisory_cases": summary.advisory_cases,
        "blocked_cases": summary.blocked_cases,
        "retention_failures": summary.retention_failure_count,
        "average_quality_improvement": summary.average_quality_improvement,
        "average_repair_time_ms": summary.average_repair_time_ms,
        "recommendation": summary.recommendation,
        "json_evidence_path": str(json_report_path),
        "text_report_path": str(text_report_path),
        "exit_code": exit_code,
    }

    return result


if __name__ == "__main__":
    result = run_skill_suite()
    sys.exit(result["exit_code"])
