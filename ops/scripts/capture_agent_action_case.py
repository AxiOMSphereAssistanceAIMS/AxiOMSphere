#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.learning_capture.case_builder import build_agent_action_case  # noqa: E402
from ops.learning_capture.models import dataclass_to_dict  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a local-agent action as learning material")
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--target-slot", required=True)
    parser.add_argument("--task-prompt-file", required=True)
    parser.add_argument("--terminal-log", default="")
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--expected-deliverables", action="append", default=[])
    parser.add_argument("--output-root", default="aims_workspace/learning_capture")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--case-id", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    case = build_agent_action_case(
        agent_name=args.agent_name,
        target_slot=args.target_slot,
        task_prompt_file=args.task_prompt_file,
        terminal_log=args.terminal_log or None,
        evidence_root=args.evidence_root,
        expected_deliverables=list(args.expected_deliverables or []),
        output_root=args.output_root,
        repo_root=args.repo_root,
        case_id=args.case_id or None,
    )
    print(json.dumps(dataclass_to_dict(case), indent=2, ensure_ascii=False))
    print(f"case_id={case.case_id}", file=sys.stderr)
    print(f"case_path={Path(args.output_root) / 'cases' / case.case_id / 'case.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
