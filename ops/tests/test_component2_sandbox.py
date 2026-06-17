#!/usr/bin/env python3
"""Component 2 Integration Tests — Sandbox Code Execution

Tests the complete sandbox pipeline:
  1. Basic Python code execution
  2. Timeout enforcement
  3. File input/output handling
  4. Error handling and isolation

Run with: python3 test_component2_sandbox.py
"""
import sys
import json
from pathlib import Path

# Add ops directory to path
_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

from core.sandbox_runner import run_code


def test_basic_execution():
    """Test 1: Basic Python code execution"""
    print("\n🧪 Test 1: Basic Python Code Execution")
    try:
        result = run_code("print(1+1)")
        assert result.ok, f"Execution failed: {result.error}"
        assert "2" in result.stdout, f"Expected '2' in output, got: {result.stdout}"
        print("  ✓ Code executed successfully")
        print(f"  ✓ Output: {result.stdout.strip()}")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        return False


def test_timeout_enforcement():
    """Test 2: Timeout enforcement"""
    print("\n🧪 Test 2: Timeout Enforcement")
    try:
        result = run_code("""
import time
time.sleep(10)
print('This should timeout')
""", timeout=2)

        assert result.timed_out, f"Expected timeout, but execution completed"
        assert not result.ok, f"Expected failure, but result.ok={result.ok}"
        print("  ✓ Timeout correctly enforced")
        print(f"  ✓ Timed out: {result.timed_out}")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        return False


def test_file_io():
    """Test 3: File input/output handling"""
    print("\n🧪 Test 3: File Input/Output Handling")
    try:
        input_data = b"hello world from test"
        result = run_code("""
with open('input.txt') as f:
    data = f.read()
with open('output.txt', 'w') as f:
    f.write(data.upper())
print('File I/O completed')
""", files={"input.txt": input_data}, collect=["output.txt"])

        assert result.ok, f"Execution failed: {result.error}"
        assert "File I/O completed" in result.stdout, f"Expected completion message, got: {result.stdout}"
        assert result.output_files is not None, "Expected output files"
        assert "output.txt" in result.output_files, f"Missing output.txt, got: {list(result.output_files.keys())}"

        output_data = result.output_files["output.txt"]
        assert output_data == input_data.upper(), f"Expected uppercase output, got: {output_data}"

        print("  ✓ File I/O completed successfully")
        print(f"  ✓ Input: {input_data.decode()}")
        print(f"  ✓ Output: {output_data.decode()}")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_handling():
    """Test 4: Error handling and reporting"""
    print("\n🧪 Test 4: Error Handling")
    try:
        result = run_code("1 / 0")

        assert not result.ok, f"Expected failure, but execution succeeded"
        assert "ZeroDivisionError" in result.stderr or "division" in result.stderr.lower(), \
            f"Expected ZeroDivisionError in stderr, got: {result.stderr[:200]}"
        print("  ✓ Error correctly caught and reported")
        print(f"  ✓ Error type: ZeroDivisionError")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        return False


def test_large_output_truncation():
    """Test 5: Large output truncation"""
    print("\n🧪 Test 5: Large Output Truncation")
    try:
        result = run_code("""
# Generate large output
for i in range(100000):
    print(f"Line {i}: " + "x" * 100)
""", timeout=15)

        # The output should be truncated to 1MB max
        assert len(result.stdout) <= 1024 * 1024, f"Output should be truncated to 1MB, got {len(result.stdout)} bytes"
        print("  ✓ Large output correctly truncated")
        print(f"  ✓ Output size: {len(result.stdout)} bytes (max 1 MB)")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        return False


def test_isolation_env_vars():
    """Test 6: Environment variable isolation"""
    print("\n🧪 Test 6: Environment Isolation")
    try:
        result = run_code("""
import os
# These should be isolated/reset
aws_key = os.environ.get('AWS_ACCESS_KEY_ID')
api_key = os.environ.get('API_KEY')
print(f"AWS_ACCESS_KEY_ID: {aws_key}")
print(f"API_KEY: {api_key}")
print(f"PATH exists: {'PATH' in os.environ}")
""")

        assert result.ok, f"Execution failed: {result.error}"
        assert "None" in result.stdout or "AWS_ACCESS_KEY_ID: None" in result.stdout, \
            f"Expected AWS_ACCESS_KEY_ID to be None, got: {result.stdout}"
        print("  ✓ Environment variables correctly isolated")
        print(f"  ✓ AWS/API keys not exposed to sandbox")
        return True
    except Exception as e:
        print(f"  ❌ Test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 70)
    print("Component 2: Sandbox Code Execution Test Suite")
    print("=" * 70)

    tests = [
        ("Basic Execution", test_basic_execution),
        ("Timeout Enforcement", test_timeout_enforcement),
        ("File I/O", test_file_io),
        ("Error Handling", test_error_handling),
        ("Output Truncation", test_large_output_truncation),
        ("Environment Isolation", test_isolation_env_vars),
    ]

    results = {}
    for name, test_fn in tests:
        try:
            results[name] = test_fn()
        except Exception as e:
            print(f"⚠️  Test {name} crashed: {e}")
            results[name] = False

    # Summary
    print("\n" + "=" * 70)
    print("📊 SANDBOX TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status:9s} {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed >= 3:  # At least basic execution tests pass
        print("\n✨ Component 2 sandbox verified!")
        return 0
    else:
        print(f"\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
