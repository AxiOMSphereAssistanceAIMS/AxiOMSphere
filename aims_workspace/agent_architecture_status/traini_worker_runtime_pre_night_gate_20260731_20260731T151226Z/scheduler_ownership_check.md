# scheduler_ownership_check

```json
{
  "redis_scheduler_container": "axiomsphere-redis-scheduler",
  "redis_scheduler_daemon": "/ops/scheduler/run_scheduler_daemon.py",
  "task_executor_runtime": "redis-scheduler",
  "direct_cron_traini_path": false,
  "cron_role": "enqueue-only for Traini support loops; Redis Scheduler owns execution",
  "night_task_direct_cron": false
}

```
