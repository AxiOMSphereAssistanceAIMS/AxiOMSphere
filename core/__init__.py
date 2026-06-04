"""Backwards-compatibility re-export shim for ops.core.

Canonical source is ops.core/ — this module exists to support legacy imports
from code that uses "from core import ..." or "from core.X import ...".

All top-level core/ modules have been unified into ops/core/ to eliminate
import ambiguity across the 300+ files using sys.path manipulation.
"""

import sys
from importlib import import_module


# Register all ops.core submodules as core.X for backwards compatibility
_SUBMODULES = [
    'errors',
    'metrics',
    'queue',
    'route_learn',
    'runtime_names',
    'sandbox_runner',
    'service_auth',
    'worker',
    'orchestrator',
    'pipeline_coordinator',
    'async_orchestrator',
    'config',
    'redis_queue',
    'worker_registry',
]

# Load direct submodules
for module_name in _SUBMODULES:
    full_name = f"ops.core.{module_name}"
    try:
        mod = import_module(full_name)
        sys.modules[f"core.{module_name}"] = mod
    except ImportError:
        pass


# Load subpackages (e.g., router)
try:
    router_mod = import_module("ops.core.router")
    sys.modules["core.router"] = router_mod
    # Also load the submodules within router
    router_model_mod = import_module("ops.core.router.model_router")
    sys.modules["core.router.model_router"] = router_model_mod
except ImportError:
    pass


# Pre-import commonly-used symbols for convenience
try:
    from ops.core.queue import TaskQueue, MemoryBackend, RedisBackend  # noqa: F401,E402
except ImportError:
    pass

try:
    from ops.core.errors import AIMSError  # noqa: F401,E402
except ImportError:
    pass

try:
    from ops.core.sandbox_runner import RunResult  # noqa: F401,E402
except ImportError:
    pass
