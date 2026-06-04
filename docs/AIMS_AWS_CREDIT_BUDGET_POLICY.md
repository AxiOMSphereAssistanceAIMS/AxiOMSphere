# AIMS AWS Credit Budget Policy

## Status

ACTIVE_TEST_PRODUCTION_POLICY

## Purpose

AIMS uses AWS Activate / AWS credits for controlled test-production development.

Credits are a shared AWS account pool. AWS Budgets do not physically split credits, but AIMS treats the current two $500 budgets as virtual operating buckets for planning and governance.

## Budget buckets

### 1. AIMS-Bedrock-Auditor-Safety

Amount: $500/month  
Alert threshold: 80% ($400)

Purpose:
- Claude Code via AWS Bedrock
- Dynamic Workflow experiments
- Bedrock auditor wrappers and gates
- Parallel Claude/Bedrock agents
- Architecture audits
- repository repair/review cycles
- controlled test-production agent work

### 2. My Zero-Spend Budget

Amount: $500/month  
Alert threshold: 80% ($400)

Purpose:
- preparation of training programs for local models
- teacher-task prompt generation
- dataset planning and review
- evaluation-suite design
- benchmark critique
- model improvement plans
- training readiness audits

## Operating rules

Allowed under this policy:
- controlled Claude Code / Bedrock use for AIMS development
- Dynamic Workflow testing
- evidence-backed audits and reviews
- training-program preparation
- dataset and evaluation planning

Not allowed without explicit approval:
- destructive cleanup
- model deletion
- model promotion / registry mutation
- live training runs
- uncontrolled external API/AWS usage
- broad service restarts
- secret exposure

## Spend governance

- Budgets are alerting controls, not hard spend limits.
- AWS credits remain a shared account-level pool.
- Cost Explorer and Billing may show usage before credits are applied.
- Credits application should be checked in Billing → Credits and Bills.
- Daily active-run monitoring should track:
  - gross Bedrock usage
  - credits applied
  - net payable cost
  - token volume where available
  - evidence folder for each major run

## Current confirmed facts

- AWS credits are active.
- Credits are applying to Amazon Bedrock usage.
- Claude Code via AWS Bedrock has been validated.
- Bedrock auditor wrappers and gates have passed.
- Dynamic Workflow usage is being offset by AWS credits.
