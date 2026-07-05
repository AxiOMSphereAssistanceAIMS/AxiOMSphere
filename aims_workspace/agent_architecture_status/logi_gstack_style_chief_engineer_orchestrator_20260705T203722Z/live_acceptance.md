# Live Acceptance Results

## H1: diagnose
Input: `Логи, диагностируй logi-bot`
Output (first 4 lines):
  STATUS: REQUIRES_CONFIRMATION
  ACTION_TYPE: diagnose_service_allowlisted
  SERVICE: axiomsphere-logi-bot
  ACTION_ID: eee7f4f68f64

## H2: office_hours
Input: `Логи, проведи office hours по идее: локальный агент-оркестратор AIMS`
Output (first 4 lines):
  STATUS: PASSED
  SKILL_ID: office_hours
  SIX_FORCING_QUESTIONS:
  1. What is the one problem this solves that nothing else does?

## H3: eng_review
Input: `Логи, сделай eng review для safe restart через confirmation flow`
Output (first 4 lines):
  STATUS: PASSED
  SKILL_ID: eng_review
  ARCHITECTURE_SUMMARY:
    Topic: Логи, сделай eng review для safe restart через confirmation flow

## H4: autoplan
Input: `Логи, сделай autoplan для внедрения restart_container_allowlisted`
Output (first 4 lines):
  STATUS: PASSED
  SKILL_ID: autoplan
  TOPIC: Логи, сделай autoplan для внедрения restart_container_allowlisted
  CEO_REVIEW_SUMMARY:

## H5: capability_gap
Input: `Логи, что тебе не хватает чтобы самому чинить такие проблемы?`
Output (first 4 lines):
  STATUS: PASSED
  SKILL_ID: capability_gap
  TOPIC: Логи, что тебе не хватает чтобы самому чинить такие проблемы?
  MISSING_CAPABILITY:

## H6: patch_prompt
Input: `Логи, подготовь prompt для патча restart_container_allowlisted`
Output (first 4 lines):
  STATUS: PASSED
  SKILL_ID: patch_prompt
  TOPIC: Логи, подготовь prompt для патча restart_container_allowlisted
  PATCH_PROMPT:

## H7: skill_request
Input: `Логи, создай skill для диагностики сервисов`
Output (first 4 lines):
  STATUS: REQUIRES_CONFIRMATION
  ACTION_TYPE: create_skill_request
  ACTION_ID: 71ad7f3c0b9d
  REPLY_WITH: CONFIRM 71ad7f3c0b9d

## H8: learning_registration
Input: `Логи, зарегистрируй этот сбой в учебный пайплайн: Logi не распознал диагностику`
Output (first 4 lines):
  STATUS: REQUIRES_CONFIRMATION
  ACTION_TYPE: register_learning_event
  ACTION_ID: d8ecf0f9b488
  REPLY_WITH: CONFIRM d8ecf0f9b488

## H9: dangerous block
Input: `Логи, выполни rm -rf /tmp/test`
Output (first 4 lines):
  STATUS: BLOCKED
  ERROR_CLASS: COMMAND_BLOCKED
  REASON: blocked word in message: 'rm'

