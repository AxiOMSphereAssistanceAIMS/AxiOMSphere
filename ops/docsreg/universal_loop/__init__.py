"""Universal improvement loop for DOCSREG self-evolving quality maximization.

Bi-nested architecture:
- Inner cycle: document generation → validation → diagnosis → repair → terminal decision
- Outer cycle: failure aggregation → recurrence detection → capability modification
"""

from ops.docsreg.universal_loop.terminal_state import TerminalState
from ops.docsreg.universal_loop.context import UniversalLoopContext, LoopDependencies
from ops.docsreg.universal_loop.stage_result import StageResult, StageOutcome
from ops.docsreg.universal_loop.result import UniversalLoopResult
from ops.docsreg.universal_loop.cycle import (
    run_universal_improvement_loop,
    UniversalImprovementLoop,
)
from ops.docsreg.universal_loop.data_retention_validator import (
    DataRetentionValidator,
    DataRetentionReport,
    DocumentSnapshot,
    RetentionVerdict,
)
from ops.docsreg.universal_loop.contracts import (
    DocumentGenerator,
    QualityValidator,
    QualityScorer,
    ContentAuditor,
    RepairService,
    SnapshotBuilder,
)
from ops.docsreg.universal_loop.evidence import EvidenceStore

__all__ = [
    # Core orchestration
    "run_universal_improvement_loop",
    "UniversalImprovementLoop",
    # State & context
    "UniversalLoopContext",
    "LoopDependencies",
    "UniversalLoopResult",
    # Stages & outcomes
    "StageResult",
    "StageOutcome",
    "TerminalState",
    # Data retention
    "DataRetentionValidator",
    "DataRetentionReport",
    "DocumentSnapshot",
    "RetentionVerdict",
    # Contracts
    "DocumentGenerator",
    "QualityValidator",
    "QualityScorer",
    "ContentAuditor",
    "RepairService",
    "SnapshotBuilder",
    # Evidence
    "EvidenceStore",
]
