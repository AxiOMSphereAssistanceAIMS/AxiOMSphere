# AIMS Bedrock Auditor Stage 1 Status

## Status

BEDROCK_AUDITOR_STAGE1_DRY_RUN_READY

## Scope

AWS Bedrock Claude auditor has been configured for controlled AIMS dry-run use.

This is not yet a production release gate.

## Configuration

- Provider: AWS Bedrock
- Region: us-west-2
- Default auditor model/profile: us.anthropic.claude-sonnet-4-6
- IAM user: aims-bedrock-auditor
- Console access: disabled
- IAM permissions:
  - bedrock:InvokeModel
  - bedrock:InvokeModelWithResponseStream
  - bedrock:ListFoundationModels
  - bedrock:GetFoundationModel
  - bedrock:ListInferenceProfiles
  - bedrock:GetInferenceProfile

## Implemented files

- ops/tools/aims_bedrock_auditor_smoke.py
- ops/tools/aims_bedrock_auditor_review.py
- ops/evals/bedrock_auditor_smoke_gate.py
- ops/evals/bedrock_auditor_review_gate.py

## Evidence

- CLI direct Bedrock invoke: PASS
- Python smoke wrapper: PASS
- Smoke gate: PASS
- Review wrapper: PASS
- Review gate: PASS_WITH_AUDITOR_WARN
- Secret file stored outside repository: PASS
- Git secret grep for AWS_SECRET_ACCESS_KEY: CLEAN

## Current limitations

- Gate is approved only for controlled dry-run use.
- Production release-gate use requires:
  - DLP / secret scanning before Bedrock invocation
  - escalation matrix for Sonnet → Opus
  - evidence retention policy
  - cost attribution / budget filter once AWS cost data is available
  - model drift detection

## Spend control

- AWS Activate credits confirmed.
- Temporary safety budget exists.
- First usage is low-token smoke/review testing only.
