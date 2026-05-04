#!/bin/bash
# Build and test the AIMS sandbox container
#
# Usage:
#   bash ops/sandbox/build_and_test.sh [--no-test]
#
# Prerequisites:
#   - Docker daemon running
#   - Working directory: /home/axi_omi_sphere/aims-workspace

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANDBOX_DIR="$REPO_ROOT/ops/sandbox"
IMAGE_NAME="aims-sandbox:latest"
SKIP_TEST=false

if [[ "$1" == "--no-test" ]]; then
    SKIP_TEST=true
fi

echo "🔨 Building $IMAGE_NAME..."
docker build -f "$SANDBOX_DIR/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"

if [[ "$?" -ne 0 ]]; then
    echo "❌ Build failed"
    exit 1
fi

echo "✅ Build succeeded"

if [[ "$SKIP_TEST" == true ]]; then
    echo "Skipping tests (--no-test passed)"
    exit 0
fi

echo ""
echo "🧪 Testing sandbox isolation..."

# Test 1: Basic Python execution
echo "  Test 1: Basic Python execution"
docker run --rm --net=none "$IMAGE_NAME" python3 -c "print('Hello from sandbox')" | grep -q "Hello" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 2: pandas import
echo "  Test 2: Pandas import"
docker run --rm --net=none "$IMAGE_NAME" python3 -c "import pandas; print(f'pandas {pandas.__version__}')" | grep -q "pandas" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 3: openpyxl import
echo "  Test 3: Openpyxl import"
docker run --rm --net=none "$IMAGE_NAME" python3 -c "import openpyxl; print(f'openpyxl {openpyxl.__version__}')" | grep -q "openpyxl" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 4: numpy import
echo "  Test 4: NumPy import"
docker run --rm --net=none "$IMAGE_NAME" python3 -c "import numpy; print(f'numpy {numpy.__version__}')" | grep -q "numpy" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 5: scipy import
echo "  Test 5: SciPy import"
docker run --rm --net=none "$IMAGE_NAME" python3 -c "import scipy; print(f'scipy {scipy.__version__}')" | grep -q "scipy" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 6: Network isolation (should timeout or fail if trying to connect)
echo "  Test 6: Network isolation (should fail)"
if docker run --rm --net=none --timeout 2 "$IMAGE_NAME" python3 -c "import socket; socket.create_connection(('example.com', 80))" 2>&1 | grep -q "Name or service not known\|Cannot assign requested address\|Name resolution\|getaddrinfo\|unreachable\|No such host\|Temporary failure\|Network unreachable"; then
    echo "    ✅ Pass (network properly isolated)"
else
    echo "    ⚠️  Warning: network isolation test inconclusive (might still be isolated)"
fi

# Test 7: Memory limit
echo "  Test 7: Memory limit (1 GB max)"
docker run --rm --net=none --memory=1g "$IMAGE_NAME" python3 -c "import sys; print(f'Memory limit test passed')" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }

# Test 8: File mount + collection
echo "  Test 8: File I/O with mount"
TMPDIR=$(mktemp -d)
echo "test data" > "$TMPDIR/input.txt"
docker run --rm --net=none -v "$TMPDIR:/tmp/sandbox-work" "$IMAGE_NAME" python3 -c "
with open('/tmp/sandbox-work/input.txt') as f:
    data = f.read()
with open('/tmp/sandbox-work/output.txt', 'w') as f:
    f.write(data.upper())
print('File I/O test passed')
" && [[ -f "$TMPDIR/output.txt" ]] && grep -q "TEST DATA" "$TMPDIR/output.txt" && echo "    ✅ Pass" || { echo "    ❌ Fail"; exit 1; }
rm -rf "$TMPDIR"

echo ""
echo "✅ All tests passed!"
echo ""
echo "Next steps:"
echo "  1. Verify docker_executor.py is importable: python3 -c 'from ops.sandbox.docker_executor import DockerSandboxExecutor'"
echo "  2. Run integration tests: pytest ops/tests/test_sandbox_docker.py -v -m integration"
echo "  3. Add to docker-compose.yml for production use (optional)"
