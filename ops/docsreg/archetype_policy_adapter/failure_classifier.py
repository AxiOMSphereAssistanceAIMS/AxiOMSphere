"""Failure classification and categorization for document repair."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from ops.docsreg.archetype_policy_adapter.base import ViolationSeverity


class FailureClass(Enum):
    """Document repair failure categories."""
    BUG = "BUG"  # Code logic error
    TIMEOUT = "TIMEOUT"  # Exceeds time budget
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"  # Memory/disk/compute
    NETWORK_ERROR = "NETWORK_ERROR"  # Connectivity issue
    POLICY_VIOLATION = "POLICY_VIOLATION"  # Archetype constraint
    OTHER = "OTHER"  # Unclassified


@dataclass(frozen=True)
class DocumentFailure:
    """Immutable record of document repair failure."""

    failure_id: str
    document_id: Optional[str]
    archetype_name: str
    failure_class: FailureClass
    severity: ViolationSeverity
    root_cause: str
    timestamp: datetime
    repair_step: str
    error_message: str
    context_excerpt: str = ""  # Up to 500 chars


class FailureClassifier:
    """Classifies document repair failures into actionable categories."""

    def classify(self, error: Exception) -> FailureClass:
        """Classify exception into FailureClass.

        Args:
            error: Exception to classify

        Returns:
            FailureClass category
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()

        # Map exception types to failure classes
        if error_type == "TimeoutError" or "timeout" in error_msg:
            return FailureClass.TIMEOUT
        elif error_type in ("MemoryError", "OutOfMemoryError") or "memory" in error_msg:
            return FailureClass.RESOURCE_EXHAUSTION
        elif error_type in ("ConnectionError", "TimeoutError") or "network" in error_msg:
            return FailureClass.NETWORK_ERROR
        elif error_type == "ValueError" and "archetype" in error_msg:
            return FailureClass.POLICY_VIOLATION
        elif error_type in ("AssertionError", "TypeError", "AttributeError"):
            return FailureClass.BUG
        else:
            return FailureClass.OTHER

    def create_failure_record(
        self,
        document_id: Optional[str],
        archetype_name: str,
        error: Exception,
        repair_step: str,
        severity: ViolationSeverity = ViolationSeverity.HIGH,
        context_excerpt: str = "",
    ) -> DocumentFailure:
        """Create failure record from exception.

        Args:
            document_id: Document identifier or None
            archetype_name: Document archetype
            error: Exception that occurred
            repair_step: Pipeline step where failure occurred
            severity: Violation severity level
            context_excerpt: Document context at failure point

        Returns:
            DocumentFailure record
        """
        failure_class = self.classify(error)
        return DocumentFailure(
            failure_id=str(uuid4()),
            document_id=document_id,
            archetype_name=archetype_name,
            failure_class=failure_class,
            severity=severity,
            root_cause=f"{type(error).__name__}: {str(error)[:200]}",
            timestamp=datetime.utcnow(),
            repair_step=repair_step,
            error_message=str(error),
            context_excerpt=context_excerpt[:500],
        )
