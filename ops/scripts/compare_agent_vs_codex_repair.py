#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.learning_capture.codex_comparison import build_codex_repair_comparison  # noqa: E402
from ops.learning_capture.models import dataclass_to_dict  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare local-agent output with Codex repair")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--codex-evidence-root", required=True)
    parser.add_argument("--codex-commit", required=True)
    parser.add_argument("--output-root", default="aims_workspace/learning_capture")
    parser.add_argument("--repo-root", default=str(ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    comparison, candidate = build_codex_repair_comparison(
        case_id=args.case_id,
        codex_evidence_root=args.codex_evidence_root,
        codex_commit=args.codex_commit,
        output_root=args.output_root,
        repo_root=args.repo_root,
    )
    result = {
        "comparison": dataclass_to_dict(comparison),
        "candidate": candidate,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"comparison_path={Path(args.output_root) / 'cases' / args.case_id / 'codex_repair_comparison.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
