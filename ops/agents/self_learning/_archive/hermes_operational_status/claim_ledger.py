from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_claim_ledger(out_dir: Path, claims: list[dict[str, Any]]) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_json = out_dir / "hermes_claim_ledger.json"
    ledger_md = out_dir / "hermes_claim_ledger.md"
    unsupported_json = out_dir / "hermes_unsupported_claims.json"

    supported = [c for c in claims if c.get("result") == "SUPPORTED"]
    unsupported = [c for c in claims if c.get("result") != "SUPPORTED"]

    ledger_json.write_text(json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
    unsupported_json.write_text(json.dumps(unsupported, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Hermes Claim Ledger",
        "",
        f"- supported_claims: {len(supported)}",
        f"- unsupported_claims: {len(unsupported)}",
        "",
        "## Claims",
    ]
    for c in claims:
        lines.append(
            f"- [{c.get('result')}] {c.get('claim_type')} :: {c.get('claim_text')} "
            f"(confidence={c.get('confidence')}, missing={','.join(c.get('missing_evidence', [])) or '-'})"
        )
    ledger_md.write_text("\n".join(lines), encoding="utf-8")
    return ledger_json, ledger_md, unsupported_json

