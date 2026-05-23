# AxiOMSphere

**Privacy-first industrial AI for source-backed engineering document workflows.**

[Website](https://axiomsphereassistanceaims.github.io/AxiOMSphere/) · [GitHub](https://github.com/AxiOMSphereAssistanceAIMS/AxiOMSphere) · [Contact](mailto:hello@axiomsphereai.com)

> **Safety statement:** AxiOMSphere supports engineering drafting and review workflows. Generated documents and recommendations require qualified human review before operational use.

> **Privacy statement:** Sensitive source documents remain on private infrastructure by default. Approved external services are used only with anonymized context for benchmarking, research or evaluation unless separately authorised.

---

## The Problem

Industrial engineering teams manage large volumes of technical procedures, maintenance instructions, shutdown documents and review comments across the asset lifecycle. Preparing and maintaining this documentation is time-consuming, error-prone and difficult to trace.

Key challenges:
- Documentation preparation for a single procedure requires input from multiple engineering disciplines across days or weeks
- Review and gap-assessment work is largely manual and depends on individual expertise
- Sensitive technical source documents require controlled handling and cannot routinely be sent to external services
- Recommendations must be traceable back to source standards and guidance materials
- Maintaining consistency across large sets of related documents during any change requires significant coordination

---

## The Solution

AxiOMSphere is a development-stage technical platform that combines local multi-agent processing with source-backed document review, while keeping sensitive materials on private infrastructure by default.

Core capabilities being validated:
- **Local document drafting** — engineering requests are processed by local language model agents without sending source documents externally
- **Source-backed review** — documents are benchmarked against relevant standards and guidance themes from the internal registry
- **OCR and document registry** — existing documents are ingested, indexed and made available to agents as structured retrieval context
- **Controlled external evaluation** — only anonymized technical context is submitted to approved external evaluators for benchmarking
- **Evidence retention** — every workflow generates traceable evidence records stored locally
- **Human review required** — all agent outputs are recommendations; qualified engineering review is required before operational use

---

## How It Works

```
Engineering request
  → Local context extraction (OCR, RAG, document registry)
  → Local document drafting or document review
    → Source-backed benchmark preparation
      → Controlled external evaluation (anonymized context only, where approved)
        → Human-reviewed output
          → Evidence and learning-case retention
```

Agents are coordinated through a local orchestration layer. No source document content leaves private infrastructure unless separately authorised.

---

## Privacy-First Architecture

| Principle | Implementation |
|-----------|----------------|
| Source documents stay local | Processed on private GPU infrastructure by default |
| External services receive only anonymized context | Benchmark and evaluation calls never include raw source documents |
| Outputs are recommendations | No automatic compliance certification; qualified engineer review required |
| Evidence is retained locally | Every workflow generates audit artifacts stored on private infrastructure |

---

## Initial Use Cases

The platform is being validated for the following workflow categories:

- **Asset preservation procedures** — drafting and reviewing preservation scope and method documents
- **Shutdown and de-preservation documentation** — procedure preparation for planned shutdown and restart sequences
- **Maintenance and reliability workflows** — maintenance instruction drafting and gap assessment
- **Technical procedure review** — structured review of existing documents against applicable standards and guidance themes
- **Engineering checklist preparation** — generating review checklists from source requirements
- **Asset management documentation** — asset register, SAMP-aligned planning documents and lifecycle records

---

## Current Development Status

| Capability | Status |
|------------|--------|
| Multi-agent orchestration workflow | Internally validated |
| Document drafting and review workflow | Implemented for internal test scenarios |
| OCR and document registry pipeline | Implemented |
| Evidence and learning-case collection | Implemented in development workflow |
| Standards and guidance benchmarking | In active development |
| Long-duration unattended validation | Planned next stage |
| External industrial pilot | Preparing |

Internal test results are maintained separately and will be shared with pilot partners under appropriate agreements.

---

## 90-Day Validation Plan

- Process 100–300 anonymized engineering review cases across target workflow categories
- Benchmark local review workflows against frontier evaluators using anonymized context
- Measure source relevance, gap-detection quality, reviewer usefulness and cost per workflow
- Prepare a controlled industrial pilot proposal based on validation findings

---

## Why We Are Seeking Startup Credits

| Resource requested | Intended use |
|-------------------|--------------|
| API credits | External evaluation benchmarks and anonymized standards and guidance discovery |
| GPU / cloud compute | Local-model inference scaling and controlled evaluation experiments |
| Storage / search services | Retrieval and document-metadata scale testing |
| Monitoring / security tooling | Secure pilot infrastructure preparation |

Credits support controlled validation — not unrestricted autonomous deployment. All external use follows the privacy architecture described above.

---

## Responsible Use

- Qualified human engineering review is required before any output is used operationally
- The platform does not claim to independently certify compliance with any standard
- Copyrighted standards and guidance documents are referenced as benchmarks, not reproduced
- Every recommendation is accompanied by traceable evidence from source materials
- Sensitive documents are handled on private infrastructure by default

---

## Technology

The platform runs on private GPU infrastructure using:

- Python, Docker, Redis, Qdrant
- Local open-weight language models via Ollama
- Vector search for document retrieval
- Prometheus and Grafana for operational monitoring
- Provider-abstracted external evaluation for benchmarking

---

## Contact

**hello@axiomsphereai.com**

For pilot discussion enquiries, API and cloud credit applications, or research collaboration.

---

## License

[MIT License](LICENSE)

---

*AxiOMSphere is in active development. All capability descriptions reflect internal development and test scenarios unless explicitly stated otherwise.*
