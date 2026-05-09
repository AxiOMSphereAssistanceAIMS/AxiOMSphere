#!/usr/bin/env python3
"""Self-learning orchestrator for the AIMS fine-tuning pipeline.

Called from ingest_standards.py, standards_rag.py, doc_agent.py.
All self-learning flows route through this module.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime

log = logging.getLogger(__name__)

ROOT = pathlib.Path(os.environ.get("AIMS_WORKSPACE", "/home/axi_omi_sphere/aims-workspace"))
NIM_SYNTH_DIR = ROOT / "ops/ft/data/nim_synth"
NIM_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
BULK_MODEL = os.environ.get("OMNIROUTE_MODEL", "gemini-free-fallback")

# Teacher combo env overrides — fall back to BULK_MODEL if not set
_EXTRACT_MODEL = os.environ.get("OMNIROUTE_EXTRACT_MODEL", BULK_MODEL)
_EXPERT_MODEL  = os.environ.get("OMNIROUTE_EXPERT_MODEL",  BULK_MODEL)
_TEACHER_MODEL = os.environ.get("OMNIROUTE_TEACHER_MODEL", BULK_MODEL)

CANONICAL_ACTIONS = {
    "classify_doc", "find_duplicates", "reassign_doc", "create_master",
    "generate_report", "search", "clarify", "handoff_axi", "answer",
}

SYSTEM_PROMPT = (
    "You are Omi — AIMS document registry archiver. "
    "Always respond with a single JSON object only. "
    "Respond ONLY with a JSON object using one of these actions: "
    + ", ".join(sorted(CANONICAL_ACTIONS))
)


def on_ingest(standard_id: str, doc_type: str, clauses: list) -> int:
    """Generate Q&A pairs from ingested document clauses.

    Args:
        standard_id: Identifier like "ISO_45001_2018"
        doc_type: e.g. "standard", "procedure"
        clauses: list of str or objects with .text attribute

    Returns:
        Number of pairs written.
    """
    api_key = os.environ.get("OMNIROUTE_API_KEY", os.environ.get("NVIDIA_API_KEY", "ollama"))

    try:
        from openai import OpenAI
    except ImportError:
        log.warning("self_learn.on_ingest: openai not installed — skipping")
        return 0

    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)
    NIM_SYNTH_DIR.mkdir(parents=True, exist_ok=True)

    texts = []
    for c in clauses:
        if isinstance(c, str):
            texts.append(c.strip())
        elif hasattr(c, "text"):
            texts.append(c.text.strip())
        elif isinstance(c, dict):
            texts.append((c.get("text") or c.get("content", "")).strip())
    texts = [t for t in texts if len(t) > 30]

    if not texts:
        return 0

    batch_size = 5
    pairs = []
    for i in range(0, min(len(texts), 50), batch_size):
        batch = texts[i:i + batch_size]
        batch_text = "\n\n".join(f"[{j+1}] {t}" for j, t in enumerate(batch))
        prompt = (
            f"You are generating training data for an AIMS document archiver called Omi.\n"
            f"Given these clauses from a {doc_type} ({standard_id}), generate {len(batch)} "
            f"question-answer pairs. Omi responds ONLY with JSON using one action from: "
            f"{', '.join(sorted(CANONICAL_ACTIONS))}.\n\n"
            f"Clauses:\n{batch_text}\n\n"
            f"Output a JSON array of objects: "
            f'[{{"prompt": "user question", "completion": {{"action": "...", ...}}}}]\n'
            f"Respond with only the JSON array."
        )
        try:
            resp = client.chat.completions.create(
                model=_EXTRACT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.7,
            )
            raw = resp.choices[0].message.content.strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                continue
            items = json.loads(raw[start:end])
            for item in items:
                p = item.get("prompt", "").strip()
                c = item.get("completion")
                if not p or not c:
                    continue
                if isinstance(c, dict):
                    if c.get("action") not in CANONICAL_ACTIONS:
                        continue
                    c = json.dumps(c, ensure_ascii=False)
                try:
                    obj = json.loads(c)
                    if obj.get("action") not in CANONICAL_ACTIONS:
                        continue
                except Exception:
                    continue
                pairs.append({
                    "prompt": p,
                    "completion": c,
                    "source": f"self_learn/on_ingest/{_EXTRACT_MODEL}",
                    "domain": "oil_gas",
                    "standard_id": standard_id,
                    "generated_at": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            log.warning("self_learn.on_ingest batch %d error: %s", i, e)

    if not pairs:
        return 0

    date_str = datetime.utcnow().strftime("%Y%m%d")
    out_path = NIM_SYNTH_DIR / f"{standard_id}_{date_str}.jsonl"
    with open(out_path, "a") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    log.info("self_learn.on_ingest: wrote %d pairs → %s", len(pairs), out_path)
    return len(pairs)


def on_generation(
    request: str,
    local_text: str,
    score: float,
    cloud_text: str | None = None,
    domain: str = "oil_gas",
) -> None:
    """Save a training pair from a DocAgent generation output.

    Args:
        request: The user's original request
        local_text: What the local model produced
        score: NIM quality score (0.0-1.0) already computed
        cloud_text: Cloud reference text (generated if None and score < 0.85)
        domain: e.g. "oil_gas"
    """
    try:
        from docagent import nvidia_nim
    except ImportError:
        log.warning("self_learn.on_generation: nvidia_nim not available")
        return

    if cloud_text is None and score < 0.85:
        try:
            cloud_text = nvidia_nim.generate_reference(request, local_text, model=_TEACHER_MODEL)
        except Exception as e:
            log.warning("self_learn.on_generation: generate_reference failed: %s", e)
            return

    try:
        nvidia_nim.save_quality_pair(
            prompt=request,
            local_output=local_text,
            cloud_output=cloud_text or local_text,
            pair_score=score,
            domain=domain,
        )
    except Exception as e:
        log.warning("self_learn.on_generation: save_quality_pair failed: %s", e)


def from_eval(score: float, context: dict) -> None:
    """Record eval failure and generate a DPO training pair for correction.

    Called after any eval run where the local model scored below threshold.

    Args:
        score:   NIM quality score 0.0–1.0 (already computed by caller)
        context: dict with keys:
                   request    — original user request (str)
                   local_text — local model output (str)
                   cloud_text — cloud reference (str, optional; generated if absent)
                   domain     — e.g. "oil_gas" (default)
    """
    # 1. Record in failure bus regardless of score
    try:
        import sys as _sys
        _ops_dir = str(ROOT / "ops")
        if _ops_dir not in _sys.path:
            _sys.path.insert(0, _ops_dir)
        from failure_detector import get_detector
        get_detector().from_eval(score, context)
    except Exception as e:
        log.warning("self_learn.from_eval: failure_detector unavailable: %s", e)

    # 2. Generate training pair only for genuinely bad outputs
    if score >= 0.85:
        return

    request = context.get("request", "")
    local_text = context.get("local_text", "")
    cloud_text = context.get("cloud_text")
    domain = context.get("domain", "oil_gas")

    if not request or not local_text:
        log.warning("self_learn.from_eval: missing request or local_text — skipping pair")
        return

    try:
        from docagent import nvidia_nim
    except ImportError:
        log.warning("self_learn.from_eval: nvidia_nim not available — skipping pair")
        return

    if cloud_text is None:
        try:
            cloud_text = nvidia_nim.generate_reference(request, local_text, model=_TEACHER_MODEL)
        except Exception as e:
            log.warning("self_learn.from_eval: generate_reference failed: %s", e)
            return

    try:
        nvidia_nim.save_quality_pair(
            prompt=request,
            local_output=local_text,
            cloud_output=cloud_text,
            pair_score=score,
            domain=domain,
        )
        log.info("self_learn.from_eval: saved DPO pair score=%.2f domain=%s", score, domain)
    except Exception as e:
        log.warning("self_learn.from_eval: save_quality_pair failed: %s", e)


def on_rag_query(question: str, local_answer: str, clauses: list) -> None:
    """Compare a RAG answer against NIM reference; save DPO pair if delta > threshold.

    Args:
        question: The user's query
        local_answer: Answer produced by local RAG pipeline
        clauses: Retrieved clause objects (unused currently, reserved for context)
    """
    try:
        from docagent import nvidia_nim
    except ImportError:
        log.warning("self_learn.on_rag_query: nvidia_nim not available")
        return

    try:
        score_val, feedback = nvidia_nim.score(question, local_answer, model=_EXPERT_MODEL)
    except Exception as e:
        log.warning("self_learn.on_rag_query: score failed: %s", e)
        return

    log.info("self_learn.on_rag_query: score=%.2f for question=%r", score_val, question[:80])

    if score_val >= 0.85:
        return

    try:
        cloud_text = nvidia_nim.generate_reference(question, local_answer, model=_TEACHER_MODEL)
        nvidia_nim.save_quality_pair(
            prompt=question,
            local_output=local_answer,
            cloud_output=cloud_text,
            pair_score=score_val,
            domain="oil_gas",
        )
    except Exception as e:
        log.warning("self_learn.on_rag_query: save pair failed: %s", e)
