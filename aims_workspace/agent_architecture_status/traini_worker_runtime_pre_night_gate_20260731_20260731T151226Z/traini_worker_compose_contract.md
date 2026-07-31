# traini_worker_compose_contract

```json
{
  "service": "traini-worker",
  "profile": "self-learning",
  "image": "axiomsphere-traini-worker:local",
  "dockerfile": "ops/Dockerfile.traini-worker",
  "working_dir": "/workspace",
  "command": [
    "sleep",
    "infinity"
  ],
  "network": "axiomsphere_net",
  "redis_endpoint": "aims-redis:6379",
  "volumes": [
    "workspace -> /workspace",
    "aims_workspace -> /workspace/aims_workspace",
    "read-only FT data/eval/train mounts"
  ],
  "compose_config_returncode": 0,
  "compose_config_excerpt": "docker-compose.yml traini-worker service inspected; no Redis dependency is required because service resolves aims-redis on the shared network."
}

```
