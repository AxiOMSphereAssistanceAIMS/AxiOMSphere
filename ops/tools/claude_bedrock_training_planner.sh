#!/usr/bin/env bash
set -euo pipefail

source "$HOME/.aims/secrets/aws_bedrock_auditor.env"

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="${AWS_DEFAULT_REGION}"

# Training-program planning agent.
# Purpose: training program preparation only, not training execution.
# Advanced mode: use Sonnet 4.6 for both main and internal fast tasks.
export ANTHROPIC_MODEL="us.anthropic.claude-sonnet-4-6"
export ANTHROPIC_SMALL_FAST_MODEL="us.anthropic.claude-sonnet-4-6"

export AIMS_AGENT_ROLE="training_program_planner"
export AIMS_AGENT_BUDGET_BUCKET="training_program_preparation"
export AIMS_AGENT_EVIDENCE_DIR="aims_workspace/training_program_agent"

mkdir -p "$AIMS_AGENT_EVIDENCE_DIR"

exec claude "$@"
