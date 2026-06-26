# Local Agent Learning Capture Status

Status: `NOT_READY`

## Summary
- Capture layer created: True
- Agent action cases log: True
- Training candidates log: True
- Skill proposals created: True
- MarkItDown case registered: True
- Codex repair linked: True
- SFT eligible: True
- DPO eligible: True
- Skill eligible: True
- Approved for training false: True
- Learning tests passed: True
- DOCSREG regression passed: False

## Evidence Paths
- Case: aims_workspace/learning_capture/cases/markitdown_slot32_training_assessment_20260626/case.json
- Comparison: aims_workspace/learning_capture/cases/markitdown_slot32_training_assessment_20260626/codex_repair_comparison.json
- DPO candidate: aims_workspace/learning_capture/cases/markitdown_slot32_training_assessment_20260626/dpo_candidate.json
- Skill proposal: aims_workspace/learning_capture/skill_proposals/docsreg-feature-completion-verification.json
- Training candidates: aims_workspace/learning_capture/training_candidates.jsonl
- DOCSREG regression log: aims_workspace/learning_capture/docsreg_regression_after_learning_capture.log

## Remaining Blockers
- aims_workspace/axi_ft_log mirror log is blocked by root-owned directory permissions; canonical learning_capture/training_candidates.jsonl was written
- DOCSREG regression command failed: 5 existing extension-gate expectation failures around .xlsx/.csv/.html/.pptx support
