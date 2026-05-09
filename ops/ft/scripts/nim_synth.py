#!/usr/bin/env python3
"""Bulk synthetic training pair generation via OmniRoute API.

Usage:
  python3 ops/ft/scripts/nim_synth.py --domain oil_gas --count 100 \
      --out ops/ft/data/nim_synth/synth_YYYYMMDD.jsonl
  python3 ops/ft/scripts/nim_synth.py --domain oil_gas --count 5 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
import time
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pip install openai", file=sys.stderr)
    sys.exit(1)

NIM_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
DEFAULT_MODEL = os.environ.get(
    "OMNIROUTE_TEACHER_MODEL",
    os.environ.get("OMNIROUTE_MODEL", "gemini-free-fallback"),
)

CANONICAL_ACTIONS = [
    "classify_doc", "find_duplicates", "reassign_doc", "create_master",
    "generate_report", "search", "clarify", "handoff_axi", "answer",
]

SYSTEM_PROMPT = (
    "You are Omi — AIMS document registry archiver. "
    "Always respond with a single JSON object only. "
    "Respond ONLY with a JSON object using one of these actions: "
    + ", ".join(CANONICAL_ACTIONS)
)

DOMAIN_CONTEXTS = {
    "oil_gas": [
        "HSE management systems", "ISO 45001 safety", "hazard identification",
        "permit to work", "LOTO procedures", "well integrity", "pipeline inspection",
        "emergency response plans", "environmental monitoring", "regulatory compliance",
        "API standards", "OSHA requirements", "process safety management",
        "SIS functional safety", "ATEX zone classification", "spill response",
        "document control", "records retention", "audit trails", "MOC procedures",
    ],
}

PROMPT_TEMPLATES = [
    "I need to {verb} the document '{doc_title}' which relates to {topic}.",
    "Can you help me find documents about {topic} in the {domain} sector?",
    "This document '{doc_title}' needs to be {verb_past} — it's a {doc_type} for {topic}.",
    "We received a new {doc_type} from {org}. Title: '{doc_title}'. What should we do with it?",
    "Is there a duplicate of '{doc_title}' in our {domain} registry?",
    "The {doc_type} '{doc_title}' from {year} needs to be archived. It covers {topic}.",
    "Generate a compliance report for {topic} based on our {domain} standards.",
    "Classify this incoming document: {doc_title} — a {doc_type} related to {topic}.",
    "What is the scope of {topic} requirements in {domain} operations?",
    "I'm looking for all documents tagged as {topic} in our system.",
]

DOC_TYPES = [
    "procedure", "standard", "policy", "manual", "checklist", "form",
    "report", "plan", "specification", "guidance document", "instruction",
]

VERBS = [
    ("archive", "archived"), ("classify", "classified"), ("register", "registered"),
    ("update", "updated"), ("review", "reviewed"), ("approve", "approved"),
]

ORGS = [
    "HSE department", "operations team", "engineering team",
    "corporate office", "site manager", "external auditor",
]


def _make_prompt(domain: str) -> str:
    ctx = DOMAIN_CONTEXTS.get(domain, DOMAIN_CONTEXTS["oil_gas"])
    topic = random.choice(ctx)
    doc_type = random.choice(DOC_TYPES)
    verb, verb_past = random.choice(VERBS)
    org = random.choice(ORGS)
    year = random.randint(2018, 2025)
    doc_title = f"{topic.title()} {doc_type.title()} {year}"
    template = random.choice(PROMPT_TEMPLATES)
    return template.format(
        verb=verb,
        verb_past=verb_past,
        doc_title=doc_title,
        doc_type=doc_type,
        topic=topic,
        domain=domain.replace("_", " "),
        org=org,
        year=year,
    )


def _make_generation_prompt(user_msg: str) -> str:
    return (
        f"You are an AI assistant generating training data for an AIMS document archiver.\n"
        f"Given this user message, produce a JSON response that Omi would give.\n"
        f"Omi must respond with ONLY a JSON object using one action from: {', '.join(CANONICAL_ACTIONS)}.\n\n"
        f"User message: {user_msg}\n\n"
        f"Respond with only the JSON object Omi would produce. Examples:\n"
        f'{{"action": "classify_doc", "doc_type": "procedure", "confidence": 0.9}}\n'
        f'{{"action": "search", "query": "safety procedures", "filters": {{"domain": "oil_gas"}}}}\n'
        f'{{"action": "clarify", "question": "Which document version should I archive?"}}\n\n'
        f"Now generate the JSON for the user message above:"
    )


def _load_exclude_prompts(exclude_file: str | None) -> frozenset[str]:
    """Load prompt strings from an existing JSONL dataset to skip during generation."""
    if not exclude_file:
        return frozenset()
    try:
        prompts: set[str] = set()
        with open(exclude_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    p = obj.get("prompt") or ""
                    # Also check messages[] for user role
                    for msg in obj.get("messages", []):
                        if msg.get("role") == "user":
                            p = msg.get("content", p)
                            break
                    if p:
                        prompts.add(p.strip())
                except json.JSONDecodeError:
                    pass
        print(f"  exclude_file: loaded {len(prompts)} existing prompts to skip")
        return frozenset(prompts)
    except Exception as e:
        print(f"  warn: could not load exclude_file {exclude_file}: {e}", file=sys.stderr)
        return frozenset()


def generate_pairs(
    client: OpenAI,
    domain: str,
    count: int,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
    temperature: float = 0.7,
    exclude_prompts: frozenset[str] = frozenset(),
) -> list[dict]:
    pairs = []
    attempts = 0
    max_attempts = count * 5

    while len(pairs) < count and attempts < max_attempts:
        attempts += 1
        user_msg = _make_prompt(domain)
        if user_msg.strip() in exclude_prompts:
            continue
        gen_prompt = _make_generation_prompt(user_msg)

        if dry_run:
            pairs.append({
                "prompt": user_msg,
                "completion": json.dumps({"action": "classify_doc", "dry_run": True}),
                "source": f"nim_synth/{model}",
                "domain": domain,
            })
            if len(pairs) >= count:
                break
            continue

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": gen_prompt}],
                max_tokens=256,
                temperature=temperature,
            )
            raw = resp.choices[0].message.content.strip()
            # extract first JSON object
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                continue
            obj = json.loads(raw[start:end])
            if obj.get("action") not in CANONICAL_ACTIONS:
                continue
            pairs.append({
                "prompt": user_msg,
                "completion": json.dumps(obj, ensure_ascii=False),
                "source": f"nim_synth/{model}",
                "domain": domain,
                "generated_at": datetime.utcnow().isoformat(),
            })
            if len(pairs) % 10 == 0:
                print(f"  generated {len(pairs)}/{count}", flush=True)
            time.sleep(0.2)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"  warn: {e}", file=sys.stderr)
            time.sleep(1)

    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="oil_gas")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--exclude-file", default=None,
                    help="JSONL dataset file — skip prompts already present in it")
    ap.add_argument("--temperature", type=float, default=0.7,
                    help="Sampling temperature (default 0.7; use 0.9+ for more diversity)")
    args = ap.parse_args()

    if args.out is None and not args.dry_run:
        date_str = datetime.utcnow().strftime("%Y%m%d")
        out_dir = pathlib.Path(__file__).parent.parent / "data/nim_synth"
        out_dir.mkdir(parents=True, exist_ok=True)
        args.out = str(out_dir / f"synth_{date_str}.jsonl")

    # Load .env if OmniRoute base URL not already in environment
    if not os.environ.get("OMNIROUTE_BASE_URL"):
        env_file = pathlib.Path(__file__).resolve().parents[3] / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get("OMNIROUTE_API_KEY") or "x"

    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)

    exclude_prompts = _load_exclude_prompts(args.exclude_file)
    print(f"Generating {args.count} pairs, domain={args.domain}, model={args.model}, temperature={args.temperature}")
    pairs = generate_pairs(
        client, args.domain, args.count, args.model, args.dry_run,
        temperature=args.temperature,
        exclude_prompts=exclude_prompts,
    )
    if args.dry_run:
        for p in pairs:
            print(json.dumps(p, ensure_ascii=False))
        print("DRY_RUN: no dataset file written")
    else:
        print(f"Generated {len(pairs)} pairs → {args.out}")
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"Done. Wrote {len(pairs)} pairs to {args.out}")


if __name__ == "__main__":
    main()
