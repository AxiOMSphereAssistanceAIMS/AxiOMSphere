# AIMS Sandbox — Isolated Code Execution

Secure sandbox for running untrusted/generated Python code with hard isolation guarantees.

## Architecture

```
┌─ User Code (axi_bot, doc_agent, etc.) ────────────────────┐
│                                                              │
│  sandbox_runner.run_code(code, files={}, collect=[])       │
│                                                              │
└─────────────────┬──────────────────────────────────────────┘
                  │
                  ├─► executor.SandboxExecutor.run()
                  │   └─► subprocess (cwd=tmpdir, no network env)
                  │       └─ Standard: used for testing, fast iteration
                  │
                  └─► docker_executor.DockerSandboxExecutor.run()
                      └─► docker run --rm --net=none aims-sandbox
                          └─ Production: kernel-level isolation
```

## Features

| Feature | Subprocess | Docker |
|---------|-----------|--------|
| Isolation | Process-level (env, cwd) | Kernel-level (network, fs) |
| Timeout | Parent process soft timeout | Container + parent timeout |
| Network | Env vars stripped | `--net=none` flag |
| Disk access | tmpdir only (soft) | Explicit mounts only (hard) |
| Resource limits | Resource module (soft) | `--memory`, `--cpus` (hard) |
| Cold start | ~50ms | ~500ms |
| Suitable for | Testing, fast local code | Production, untrusted code |

## Requirements

- Docker daemon running
- `docker` Python package: `pip install docker`
- For tests: `pytest` (run via `pytest ops/tests/ -v`)

## Building

```bash
# From repo root
docker build -f ops/sandbox/Dockerfile -t aims-sandbox:latest .

# Build and test all in one
bash ops/sandbox/build_and_test.sh

# Verify manually
docker run --rm --net=none aims-sandbox python3 -c "import pandas; print(pandas.__version__)"
```

## Usage

### Via subprocess executor (default, fast)

```python
from ops.core.sandbox_runner import run_code

result = run_code(
    """
    import pandas as pd
    df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
    print(df.describe())
    """,
    timeout=10
)
print(result.stdout)
```

### Via Docker executor (production, isolated)

```python
from ops.sandbox.docker_executor import DockerSandboxExecutor

executor = DockerSandboxExecutor(
    image="aims-sandbox:latest",
    timeout=10,
    memory_limit="1g",
    cpus_limit=1.0
)

result = executor.run(
    """
    import pandas as pd
    with open('input.csv') as f:
        df = pd.read_csv(f)
    print(len(df))
    """,
    files={"input.csv": b"x,y\n1,2\n3,4\n"},
    collect=["output.xlsx"]
)

if result.ok:
    print("Output file:", result.output_files.get("output.xlsx"))
```

## Security Model

### Network Isolation

- Docker: `--net=none` — no network namespace
- Subprocess: `PATH`, `HOME`, `TMPDIR` only; `PYTHONPATH` preserved for framework imports
- Result: Code cannot reach external APIs, databases, or network services

### Filesystem Isolation

- Docker: Only `/tmp` is writable; input files mounted at `/tmp/sandbox-work`
- Subprocess: Only `tmpdir` writable
- Result: No access to `/home`, `/etc`, or production data

### Resource Limits

- Memory: 1 GB (configurable via `memory_limit`)
- CPU: 1 core (configurable via `cpus_limit`)
- File descriptors: 512 (via ulimit in subprocess)
- Timeout: 15s wall-clock (configurable)
- Result: Runaway code cannot consume DGX/PC resources

### User Context

- Runs as non-root `sandbox` user (UID 1000)
- No `sudo`, no shell access
- No access to host SSH keys or credentials
- Result: Even if code escapes the container, it has minimal privileges

## Supported Libraries

Core:
- `pandas` — data frames, CSV/Excel I/O
- `numpy` — numerical arrays
- `scipy` — scientific computing
- `openpyxl` — Excel generation/parsing

Utilities:
- `python-dateutil` — date parsing
- `PyYAML` — YAML parsing
- `requests` — HTTP (network disabled, so fails safely)

## Testing

```bash
# Test subprocess executor
python3 -m pytest ops/tests/test_sandbox_executor.py -v

# Test Docker executor
python3 -m pytest ops/tests/test_sandbox_docker.py -v -m "integration"

# Manual test
docker build -f ops/sandbox/Dockerfile -t aims-sandbox:latest .
echo "import pandas as pd; print(pd.DataFrame({'x': [1, 2, 3]}))" | \
  docker run --rm --net=none -i aims-sandbox:latest python3
```

## Debugging

### View logs from failed execution

```python
result = run_code("1 / 0", timeout=5)
print(result.error)      # → "division by zero"
print(result.stderr)     # Full traceback
print(result.returncode) # Exit code
```

### Trace execution with strace (local only)

```bash
docker run --rm --net=none --cap-add SYS_PTRACE \
  aims-sandbox:latest strace -e openat python3 -c "import pandas"
```

### Build without cache (rebuild all layers)

```bash
docker build --no-cache -f ops/sandbox/Dockerfile -t aims-sandbox:latest .
```

## Roadmap

- [ ] Add `docker_executor.py` — Docker-based isolation (production)
- [ ] Add seccomp profile enforcement via `seccomp_openclaw.json`
- [ ] Integration test: verify no network egress (nsenter check)
- [ ] Metrics: time/memory/exit code per execution
- [ ] Auto-cleanup of stale Docker containers (timeout safety valve)

## See Also

- `executor.py` — subprocess-level isolation (current)
- `sandbox_runner.py` — high-level API (runs_code function)
- `core/sandbox_runner.py` — AIMS application wrapper
- `blueprint.yaml` — NemoClaw Claude Code sandbox policy
