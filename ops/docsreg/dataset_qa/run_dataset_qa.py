"""PHASE 9 Dataset QA Pipeline — CLI entry point."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="PHASE 9 Dataset QA Pipeline — build training/validation datasets from Phase 7/8 evidence"
    )
    parser.add_argument(
        "--input-evidence-root",
        type=str,
        required=True,
        help="Path to Phase 7 evidence directory",
    )
    parser.add_argument(
        "--output-root",
        type=str,
        required=True,
        help="Path to write Phase 9 output artifacts",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible splits (default: 42)",
    )
    args = parser.parse_args()

    evidence_root = Path(args.input_evidence_root)
    output_root = Path(args.output_root)

    if not evidence_root.exists():
        print(f"ERROR: Evidence root does not exist: {evidence_root}")
        sys.exit(1)

    print(f"PHASE 9 Dataset QA Pipeline")
    print(f"  Evidence root: {evidence_root}")
    print(f"  Output root:   {output_root}")
    print(f"  Seed:          {args.seed}")
    print()

    # Import here to keep CLI fast for --help
    from ops.docsreg.dataset_qa.dataset_builder import DatasetBuilder
    from ops.docsreg.dataset_qa.evidence_generator import DatasetEvidenceGenerator

    # Step 1: Build dataset
    print("Step 1/2: Running dataset QA pipeline...")
    builder = DatasetBuilder(seed=args.seed)
    manifest = builder.build_from_evidence(evidence_root)

    print(f"  Raw examples:        {len(builder.raw_examples)}")
    print(f"  Leakage findings:    {len(builder.leakage_findings)}")
    print(f"  Accepted:            {len(builder.accepted_examples)}")
    print(f"  Rejected:            {len(builder.rejected_examples)}")
    print(f"  After dedup:         {len(builder.deduplicated_examples)}")
    print(f"  Training set:        {len(builder.training_set)}")
    print(f"  Validation set:      {len(builder.validation_set)}")
    print()

    # Step 2: Generate evidence
    print("Step 2/2: Generating evidence files...")
    generator = DatasetEvidenceGenerator(output_root)
    files = generator.generate_all(
        training_set=builder.training_set,
        validation_set=builder.validation_set,
        rejected_examples=builder.rejected_examples,
        manifest=manifest,
        quality_report=builder.quality_report,
        leakage_findings=builder.leakage_findings,
        dedup_result=builder.dedup_result,
        balance_report=builder.balance_report,
    )

    print(f"  Generated {len(files)} evidence files:")
    for f in files:
        print(f"    - {f.name}")
    print()

    # Summary
    passes = builder.quality_report.passes_quality_gate if builder.quality_report else False
    verdict = "READY" if passes else "NOT_READY"
    print(f"Quality gate verdict: {verdict}")
    print(f"All gates pass:       {manifest.passes_all_gates}")

    # Write summary to stdout as JSON for automation
    summary = {
        "phase": "PHASE_9",
        "verdict": verdict,
        "training_count": len(builder.training_set),
        "validation_count": len(builder.validation_set),
        "rejected_count": len(builder.rejected_examples),
        "total_processed": len(builder.raw_examples),
        "output_root": str(output_root),
        "files_generated": len(files),
    }
    print()
    print("--- JSON SUMMARY ---")
    print(json.dumps(summary, indent=2))

    return 0 if passes else 1


if __name__ == "__main__":
    sys.exit(main())
