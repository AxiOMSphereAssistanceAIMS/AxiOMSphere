"""
Logi Learning Loop — Task → Draft → Claude Code Review → Lesson → Execution → Training Data

Architecture:
1. Task → Logi
2. Logi calls local model → draft solution
3. Draft → Claude Code CLI review
4. Claude provides correction/policy review
5. Logi registers as lesson (memory)
6. Logi executes correct solution
7. Errors become training data
8. Training data improves Logi's future solutions

This is how Logi learns and improves from each task.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class LessonStatus(Enum):
    """Status of a registered lesson."""
    REGISTERED = "registered_from_correction"
    APPLIED = "applied_in_execution"
    VALIDATED = "validated_by_success"
    EVIDENCE_COLLECTED = "error_evidence_collected"


@dataclass
class TaskToSolution:
    """Record of task → draft solution → correction → lesson."""
    task_id: str
    task_text: str
    logi_draft: Dict[str, Any]
    claude_code_correction: Dict[str, Any]
    differences: List[str]
    lesson_registered: bool = False
    execution_successful: bool = False
    errors_encountered: Optional[List[str]] = None
    training_data_generated: bool = False
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"
        if self.errors_encountered is None:
            self.errors_encountered = []


@dataclass
class RegisteredLesson:
    """A lesson learned by Logi from Claude Code correction."""
    lesson_id: str
    task_id: str
    error_pattern: str
    correction_applied: str
    why_important: str
    similar_situations: List[str]
    status: LessonStatus = LessonStatus.REGISTERED
    applied_count: int = 0
    validation_count: int = 0
    training_data_used: bool = False
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


@dataclass
class TrainingDataCandidate:
    """Training data generated from Logi's learning loop."""
    candidate_id: str
    source_lesson_id: str
    source_task_id: str
    error_type: str
    weak_solution: str
    corrected_solution: str
    improvement_reason: str
    target_model: str  # Which Logi model this is for
    quality_score: float  # 0.0-1.0
    ready_for_training: bool = False
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


class LogiMemory:
    """Logi's memory and lesson registry."""

    def __init__(self):
        """Initialize Logi's memory."""
        self.tasks_processed: Dict[str, TaskToSolution] = {}
        self.lessons_registered: Dict[str, RegisteredLesson] = {}
        self.training_data_candidates: Dict[str, TrainingDataCandidate] = {}

    def register_task_to_solution(
        self,
        task_text: str,
        logi_draft: Dict[str, Any],
        claude_code_correction: Dict[str, Any],
    ) -> TaskToSolution:
        """
        Register a task → draft → correction cycle.

        Args:
            task_text: The original task
            logi_draft: Logi's draft solution (before review)
            claude_code_correction: Claude Code CLI's review and correction

        Returns:
            TaskToSolution record
        """
        task_id = f"task-{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        # Identify differences
        differences = self._identify_differences(logi_draft, claude_code_correction)

        record = TaskToSolution(
            task_id=task_id,
            task_text=task_text,
            logi_draft=logi_draft,
            claude_code_correction=claude_code_correction,
            differences=differences,
        )

        self.tasks_processed[task_id] = record
        return record

    def register_lesson(
        self,
        task_id: str,
        error_pattern: str,
        correction_applied: str,
        why_important: str,
        similar_situations: Optional[List[str]] = None,
    ) -> RegisteredLesson:
        """
        Register a lesson learned from Claude Code correction.

        Args:
            task_id: The task that taught this lesson
            error_pattern: What Logi did wrong
            correction_applied: How Claude Code fixed it
            why_important: Why this matters for future tasks
            similar_situations: Similar tasks where this applies

        Returns:
            RegisteredLesson
        """
        lesson_id = f"lesson-{task_id}-{datetime.utcnow().strftime('%H%M%S')}"

        lesson = RegisteredLesson(
            lesson_id=lesson_id,
            task_id=task_id,
            error_pattern=error_pattern,
            correction_applied=correction_applied,
            why_important=why_important,
            similar_situations=similar_situations or [],
        )

        self.lessons_registered[lesson_id] = lesson

        # Mark task as having lesson registered
        if task_id in self.tasks_processed:
            self.tasks_processed[task_id].lesson_registered = True

        return lesson

    def record_execution_result(
        self,
        task_id: str,
        successful: bool,
        errors: Optional[List[str]] = None,
    ) -> None:
        """
        Record how execution went.

        Args:
            task_id: The task executed
            successful: Whether execution succeeded
            errors: Any errors encountered
        """
        if task_id in self.tasks_processed:
            record = self.tasks_processed[task_id]
            record.execution_successful = successful
            record.errors_encountered = errors or []

            # Validate lesson if execution succeeded
            if successful:
                for lesson in self.lessons_registered.values():
                    if lesson.task_id == task_id:
                        lesson.status = LessonStatus.VALIDATED
                        lesson.validation_count += 1

    def create_training_data_candidate(
        self,
        source_lesson_id: str,
        source_task_id: str,
        error_type: str,
        weak_solution: str,
        corrected_solution: str,
        improvement_reason: str,
        target_model: str = "logi",
        quality_score: float = 0.75,
    ) -> TrainingDataCandidate:
        """
        Create a training data candidate from a lesson.

        Args:
            source_lesson_id: Which lesson this is from
            source_task_id: Original task ID
            error_type: Type of error
            weak_solution: Logi's incorrect solution
            corrected_solution: Claude's correct solution
            improvement_reason: Why this is better
            target_model: Which model to improve
            quality_score: Quality of this training example

        Returns:
            TrainingDataCandidate
        """
        candidate_id = f"training-{source_lesson_id}-{datetime.utcnow().strftime('%H%M%S')}"

        candidate = TrainingDataCandidate(
            candidate_id=candidate_id,
            source_lesson_id=source_lesson_id,
            source_task_id=source_task_id,
            error_type=error_type,
            weak_solution=weak_solution,
            corrected_solution=corrected_solution,
            improvement_reason=improvement_reason,
            target_model=target_model,
            quality_score=quality_score,
        )

        self.training_data_candidates[candidate_id] = candidate

        # Mark lesson as generating training data
        if source_lesson_id in self.lessons_registered:
            self.lessons_registered[source_lesson_id].status = LessonStatus.EVIDENCE_COLLECTED
            self.lessons_registered[source_lesson_id].training_data_used = True

        return candidate

    def get_lessons_for_similar_task(self, task_keywords: List[str]) -> List[RegisteredLesson]:
        """
        Get lessons that apply to a similar task.

        Args:
            task_keywords: Keywords from the current task

        Returns:
            List of applicable lessons
        """
        applicable = []
        for lesson in self.lessons_registered.values():
            if any(kw in " ".join(lesson.similar_situations) for kw in task_keywords):
                applicable.append(lesson)
        return applicable

    def summarize_learning(self) -> Dict[str, Any]:
        """Summarize Logi's learning progress."""
        return {
            "tasks_processed": len(self.tasks_processed),
            "lessons_registered": len(self.lessons_registered),
            "lessons_validated": len(
                [l for l in self.lessons_registered.values() if l.status == LessonStatus.VALIDATED]
            ),
            "training_data_candidates": len(self.training_data_candidates),
            "training_data_ready": len(
                [c for c in self.training_data_candidates.values() if c.ready_for_training]
            ),
            "successful_executions": len(
                [t for t in self.tasks_processed.values() if t.execution_successful]
            ),
        }

    def _identify_differences(self, draft: Dict[str, Any], correction: Dict[str, Any]) -> List[str]:
        """Identify differences between draft and correction."""
        differences = []
        all_keys = set(draft.keys()) | set(correction.keys())

        for key in all_keys:
            draft_val = draft.get(key)
            correction_val = correction.get(key)

            if draft_val != correction_val:
                differences.append(
                    f"Changed {key}: {str(draft_val)[:50]} → {str(correction_val)[:50]}"
                )

        return differences


# Global memory instance
_memory = None


def get_memory() -> LogiMemory:
    """Get or create global Logi memory."""
    global _memory
    if _memory is None:
        _memory = LogiMemory()
    return _memory


__all__ = [
    "LessonStatus",
    "TaskToSolution",
    "RegisteredLesson",
    "TrainingDataCandidate",
    "LogiMemory",
    "get_memory",
]
