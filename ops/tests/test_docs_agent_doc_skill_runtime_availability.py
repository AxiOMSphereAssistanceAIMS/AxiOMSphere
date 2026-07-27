from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_docs_agent_registry_declares_a_real_executable_doc_skill():
    """docs-agent's registry entry must map its declared fullstack skill onto
    a genuine ops/docagent/doc_skills.py skill, not just a reference name."""
    registry = yaml.safe_load(
        (ROOT / "ops/agents/agent_skill_registry.yaml").read_text(encoding="utf-8")
    )
    entry = registry["agents"]["docs-agent"]
    assert "make-pdf" in entry["source_fullstack_skills"]
    doc_skills = entry["doc_skills"]
    assert doc_skills["runner"] == "ops/docagent/doc_skills.py"
    assert "doc-analyze" in doc_skills["skills"]


def test_docs_agent_doc_skill_endpoint_reaches_the_scoped_runner():
    from ops.agents.docs_agent import app

    client = TestClient(app)

    forbidden = client.post("/doc-skill", json={"skill": "doc-generate", "params": {}})
    assert forbidden.status_code == 403

    reachable = client.post(
        "/doc-skill",
        json={"skill": "doc-analyze", "params": {"source": "nonexistent_test_file.txt"}},
    )
    assert reachable.status_code != 403
    assert reachable.status_code != 503
