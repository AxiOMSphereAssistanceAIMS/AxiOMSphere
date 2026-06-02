#!/usr/bin/env bash
set -euo pipefail

source "$HOME/.aims/secrets/aws_bedrock_auditor.env"

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="${AWS_DEFAULT_REGION}"
export ANTHROPIC_MODEL="${AIMS_BEDROCK_AUDITOR_MODEL}"
export ANTHROPIC_SMALL_FAST_MODEL="us.anthropic.claude-haiku-4-5-20251001-v1:0"

exec claude "$@"
