"""
Minimal DocAgent example — generates an ISO-compliant document via the dual pipeline.

Requirements:
    pip install requests python-docx

Environment:
    GEMINI_API_KEY   — Google Gemini API key (required for quality scoring)
    DOCAGENT_URL     — DocAgent API base URL (default: http://localhost:8100)

Usage:
    python doc_agent_example.py
"""

import os
import json
import time
import requests

DOCAGENT_URL = os.environ.get("DOCAGENT_URL", "http://localhost:8100")
TIMEOUT = 600  # seconds — dual pipeline takes ~10 min end-to-end


def generate_document(user_request: str, dual_pipeline: bool = True) -> dict:
    payload = {
        "user_request": user_request,
        "dual_pipeline": dual_pipeline,
    }

    print(f"Sending request to DocAgent ({DOCAGENT_URL})...")
    resp = requests.post(f"{DOCAGENT_URL}/generate", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def main():
    user_request = (
        "Create a Job Safety Analysis for confined space entry at an underground mine. "
        "Reference ISO 45001. Include hazard table, controls hierarchy, permit conditions."
    )

    start = time.time()
    result = generate_document(user_request, dual_pipeline=True)
    elapsed = time.time() - start

    score = result.get("score", 0.0)
    feedback = result.get("feedback", "")
    doc_path = result.get("document_path", "")
    preview = result.get("preview", "")[:500]

    print(f"\nDocument: {doc_path}")
    print(f"ISO compliance score: {score:.0%}")
    print(f"Feedback: {feedback}")
    print(f"Preview:\n{preview}")
    print(f"\nCompleted in {elapsed:.0f}s")

    if score >= 0.8:
        print("\nResult saved to training data (gold pair).")


if __name__ == "__main__":
    main()
