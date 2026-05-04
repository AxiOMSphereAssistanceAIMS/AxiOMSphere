"""Integration tests for docker-based sandbox executor.

Tests require:
  - Docker daemon running
  - aims-sandbox:latest image built (run: bash ops/sandbox/build_and_test.sh)
  - docker package installed: pip install docker

Run with: pytest ops/tests/test_sandbox_docker.py -v -m integration
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestDockerSandboxExecutor(unittest.TestCase):
    """Docker-based sandbox isolation tests."""

    @classmethod
    def setUpClass(cls):
        """Check docker availability."""
        try:
            from sandbox.docker_executor import docker_available
            if not docker_available():
                raise RuntimeError("Docker daemon not running or aims-sandbox image not found")
        except ImportError as e:
            raise RuntimeError(f"docker package not installed: {e}") from e

    def test_basic_execution(self):
        """Test basic Python code execution in sandbox."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor()
        result = executor.run("print('Hello from sandbox')")

        self.assertTrue(result.ok, f"Failed: {result.error}")
        self.assertIn("Hello from sandbox", result.stdout)

    def test_pandas_import(self):
        """Test pandas is available in sandbox."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor()
        result = executor.run("""
import pandas as pd
df = pd.DataFrame({'x': [1, 2, 3]})
print(f'DataFrame shape: {df.shape}')
""")

        self.assertTrue(result.ok, f"Failed: {result.error}")
        self.assertIn("DataFrame shape: (3, 1)", result.stdout)

    def test_timeout(self):
        """Test timeout enforcement."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor(timeout=2)
        result = executor.run("""
import time
time.sleep(10)
print('This should timeout')
""")

        self.assertTrue(result.timed_out, "Expected timeout")
        self.assertFalse(result.ok)

    def test_file_io(self):
        """Test file I/O with mounted volumes."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor()
        result = executor.run(
            """
with open('/tmp/sandbox-work/input.txt') as f:
    data = f.read()
with open('/tmp/sandbox-work/output.txt', 'w') as f:
    f.write(data.upper())
print('File I/O completed')
""",
            files={"input.txt": b"hello world"},
            collect=["output.txt"]
        )

        self.assertTrue(result.ok, f"Failed: {result.error}")
        self.assertIn("File I/O completed", result.stdout)
        self.assertIsNotNone(result.output_files)
        self.assertIn("output.txt", result.output_files)
        self.assertEqual(result.output_files["output.txt"], b"HELLO WORLD")

    def test_network_isolation(self):
        """Test that network access is blocked."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor(timeout=5)
        result = executor.run("""
import socket
try:
    socket.create_connection(('example.com', 80), timeout=1)
    print('ERROR: Network access succeeded (should be blocked)')
except Exception as e:
    print(f'Network correctly blocked: {type(e).__name__}')
""")

        # Network should be blocked, so connection should fail
        self.assertIn("Network correctly blocked", result.stdout)

    def test_error_handling(self):
        """Test error reporting."""
        from sandbox.docker_executor import DockerSandboxExecutor

        executor = DockerSandboxExecutor()
        result = executor.run("1 / 0")

        self.assertFalse(result.ok)
        self.assertIn("ZeroDivisionError", result.stderr)


if __name__ == "__main__":
    unittest.main()
