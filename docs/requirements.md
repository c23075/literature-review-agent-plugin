# Requirements

Moved from Cairnward's requirements with ADR-0017.

### Research workflows
| ID | Requirement | Pri | MS | Verification |
|---|---|---|---|---|
| FR-RES-1 | PDF library from a local folder (pypdfium2 default; Docling optional worker), chunks, embeddings | M | M1 | integration |
| FR-RES-2 | `lit.ask`: answers with page citations | M | M1 | eval `evals/pdf_qa` |
| FR-RES-3 | Research jobs: queue, progress, resumable after restart, schedulable | M | M1 | `test_jobs_resume.py` |
| FR-RES-4 | Review pipeline: screen (abstracts) → extract (full text), both with the main model (D63) → synthesise → comparison table + `.bib`; work grouped by model; estimated finish time | M | M3 | eval `evals/litreview_table` |
| FR-RES-5 | Citation check: every reference resolves; every quotation matches PDF text | M | M1 | `test_citation_check.py`, eval `evals/citation_existence` (the checker), `evals/pdf_qa` (real answers, zero invented) |
| FR-RES-6 | CSL formatting; APA and IEEE shipped; `.csl` adds styles | M | M1 | golden tests |
| FR-RES-7 | Zotero via local API | S | M3 | fake Zotero API |
| FR-RES-8 | arXiv search (opt-in, cached, audited) | M | M3 | recorded responses |
| FR-RES-9 | Semantic Scholar, OpenAlex, PubMed, Crossref | S | M3 | recorded responses |
| FR-RES-10 | Research tools exposed via MCP (`lit.search`, `lit.ask`, `lit.review.start`) | M | M2 | integration |
| FR-RES-11 | Sub-agent fan-out in workflows with budgets, `max_parallel`, nested audit; YAML workflows | S | M3 | `test_workflow.py`; not yet run with a real model |
| FR-RES-12 | PaperQA2 spike with written recommendation | M | M1 | ADR-0014 ✅ |
| FR-RES-13 | Optional PaperQA2 "deep" engine as a sandboxed worker (all calls through the gateway, hosted defaults off), compared with the lean pipeline on the same evals | S | M3 | `tests/test_paperqa_guard.py`, `tests/isolation/test_paperqa_engine.py` ✅; `evals/pdf_qa --compare` (owner-side, real models) |

