from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"(?i)(token|password|secret|bearer)\s*[:=]\s*[^\s\"']+"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+[a-z0-9._\-]+"),
    re.compile(r"(?i)(sk-[a-z0-9]{10,})"),
    re.compile(r"(?i)(xox[baprs]-[a-z0-9\-]{10,})"),
]

ENV_VALUE_PATTERN = re.compile(r"^([A-Z0-9_]+)=([^\n]+)$", re.M)


def _sanitize_text(text: str) -> tuple[str, int]:
    redactions = 0
    out = text
    for pat in SECRET_PATTERNS:
        out2, n = pat.subn("<REDACTED_SECRET>", out)
        out = out2
        redactions += n

    def repl_env(m: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return f"{m.group(1)}=<REDACTED_VALUE>"

    out = ENV_VALUE_PATTERN.sub(repl_env, out)
    out = out.replace(".claude-mem", "<REDACTED_CLAUDE_MEM_PATH>")
    out = out.replace("raw claude-mem", "<REDACTED_CLAUDE_MEM_CONTENT>")
    return out, redactions


def sanitize_obj(obj: Any) -> tuple[Any, int]:
    if isinstance(obj, str):
        return _sanitize_text(obj)
    if isinstance(obj, list):
        total = 0
        out = []
        for item in obj:
            s, n = sanitize_obj(item)
            total += n
            out.append(s)
        return out, total
    if isinstance(obj, dict):
        total = 0
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k.lower() in {"password", "token", "api_key", "secret", "bearer", "cookies"}:
                out[k] = "<REDACTED_SECRET>"
                total += 1
                continue
            s, n = sanitize_obj(v)
            total += n
            out[k] = s
        return out, total
    return obj, 0
