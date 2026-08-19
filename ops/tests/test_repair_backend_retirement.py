import pytest

from ops.repairman.claude_code_repair_backend import RepairmanBackendError, run_repair_backend
from ops.repairman.repair_request_schema import FailureRepairRequest


def test_legacy_repair_backend_is_not_an_execution_fallback(monkeypatch):
    monkeypatch.setenv("REPAIRMAN_BACKEND", "legacy")
    request = FailureRepairRequest(request_id="r1", source_agent="LOGI", source_pipeline="test", failure_origin="test_failure", failure_summary="test")
    with pytest.raises(RepairmanBackendError, match="LEGACY_REPAIR_BACKEND_RETIRED"):
        run_repair_backend(request, {}, allow_legacy_fallback=True)
