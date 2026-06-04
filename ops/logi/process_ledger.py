"""Process Ledger — records every Logi action for audit and replay.

Every action, iteration, dispatch, collection, comparison, corrective step,
and final decision is written to an append-only JSONL ledger. Immutable once written.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessLedger:
    """Append-only JSONL ledger for one process integrity run."""

    def __init__(self, goal_id: str, run_dir: Path) -> None:
        self.goal_id = goal_id
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._path = run_dir / "ledger.jsonl"
        self._entries: list[dict[str, Any]] = []

    # ── core record ───────────────────────────────────────────────────────────

    def record(
        self,
        event_type: str,
        data: dict[str, Any],
        status: str = "OK",
        agent: str = "",
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "goal_id": self.goal_id,
            "timestamp": _now(),
            "event_type": event_type,
            "status": status,
            "agent": agent,
        }
        entry.update(data)
        self._entries.append(entry)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # ── typed helpers ─────────────────────────────────────────────────────────

    def iteration_start(self, iteration: int) -> dict:
        return self.record("iteration_start", {"iteration": iteration})

    def iteration_end(self, iteration: int, decision: str) -> dict:
        return self.record("iteration_end", {"iteration": iteration, "decision": decision})

    def dispatch(self, step_title: str, agent: str, tool: str, payload: dict) -> dict:
        return self.record(
            "dispatch",
            {"step": step_title, "tool": tool, "payload_keys": list(payload.keys())},
            agent=agent,
        )

    def collect(self, step_title: str, agent: str, result_summary: str, status: str) -> dict:
        return self.record(
            "collect",
            {"step": step_title, "result_summary": result_summary[:400]},
            status=status,
            agent=agent,
        )

    def compare(self, criterion: str, actual: str, expected: str, status: str) -> dict:
        return self.record(
            "compare",
            {"criterion": criterion, "actual": actual[:200], "expected": expected[:200]},
            status=status,
        )

    def corrective(
        self,
        action_id: str,
        reason: str,
        agent: str,
        action: str,
        result: str,
        status: str,
    ) -> dict:
        return self.record(
            "corrective_action",
            {"action_id": action_id, "reason": reason, "action": action, "result": result[:400]},
            status=status,
            agent=agent,
        )

    def gap(self, tool: str, error: str, gap_report: dict) -> dict:
        return self.record(
            "capability_gap",
            {"tool": tool, "error": error[:300], "gap": gap_report},
            status="GAP",
        )

    def deliver(self, method: str, status: str, detail: str) -> dict:
        return self.record(
            "delivery",
            {"method": method, "detail": detail[:400]},
            status=status,
        )

    # ── queries ───────────────────────────────────────────────────────────────

    def all_entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self._entries if e["event_type"] == event_type]

    def summary(self) -> dict[str, Any]:
        by_event: dict[str, int] = {}
        for e in self._entries:
            et = e["event_type"]
            by_event[et] = by_event.get(et, 0) + 1
        return {
            "goal_id": self.goal_id,
            "total_entries": len(self._entries),
            "path": str(self._path),
            "by_event_type": by_event,
        }

    def write_summary(self) -> Path:
        path = self.run_dir / "ledger_summary.json"
        path.write_text(json.dumps(self.summary(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
