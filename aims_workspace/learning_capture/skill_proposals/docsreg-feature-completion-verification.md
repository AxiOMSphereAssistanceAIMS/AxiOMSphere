# Skill Proposal: docsreg-feature-completion-verification

Status: PROPOSED
Approved for training: false
Requires human approval: true

## Failure Modes
- evidence_only_completion_without_feature_implementation
- missing_artifact_paths
- missing_learning_entry
- no_commit_after_implementation

## Cases
- markitdown_slot32_training_assessment_20260626

## Checklist
1. Compare requested deliverables against actual files.
2. Verify production files exist in repo, not only evidence.
3. Verify entrypoint/wiring exists.
4. Verify tests exist and pass.
5. Verify limited production run exercises the new implementation.
6. Verify no mocked path is claimed as production.
7. If requested files are missing, report NOT READY, not COMPLETE.
