# Challenge C06 — Training Loop: When Does It Fire and Why Doesn't It?

## Symptom

Quality has been below 82% for 3 weeks. 67 training pairs are in OMI.
The training loop has not fired. No error in any log.

## Known configuration

- `orchestrator.py:check_training_triggers()` threshold: `training_pairs >= 50 OR eval_quality < 82`
- `traini_agent` is running on port 8007, health=ok
- `/check_training` endpoint exists on the orchestrator (port 8000)
- `axi_bot.py` does NOT call `/check_training` anywhere
- No cron job calls `/check_training`

## Your task

1. Confirm that the bug is architectural: nothing calls `check_training_triggers()` automatically.
2. Check `aims_scheduler.py` and `schedule.yaml` to see if a scheduled job exists for this.
3. Check `argus_agent.py` to see if it emits a training trigger event.
4. Propose the minimal wiring to make the training loop fire automatically.
   Two valid approaches: (a) ArgusAgent calls `/check_training` after each health report,
   or (b) a scheduler cron job calls `/check_training` on a schedule.
   Pick one and write the code/config change.
5. Explain what `traini_agent.py` does when triggered — trace the call through to
   the actual fine-tuning subprocess.

## What we're testing

- Understands that `check_training_triggers()` is never called automatically
- Reads schedule.yaml and aims_scheduler.py to confirm no scheduled call
- Reads argus_agent.py to confirm it doesn't emit training events
- Proposes correct minimal wiring
- Traces traini_agent.py internals

## Grading

| Criterion | Points |
|-----------|--------|
| Correctly identifies the missing caller as root cause | 25 |
| Reads schedule.yaml / aims_scheduler.py to confirm gap | 20 |
| Reads argus_agent.py to confirm it doesn't call /check_training | 15 |
| Correct minimal wiring proposal with actual code/config | 30 |
| Traces traini_agent.py trigger path | 10 |
| **Total** | **100** |
