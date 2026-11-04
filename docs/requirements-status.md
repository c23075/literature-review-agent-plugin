# Requirements status

As of the move from Cairnward (2026-11-05). Test names are this repository's. The review results are in docs/bench.

### Research
| ID | Status | Notes |
|---|---|---|
| FR-RES-1 PDF library | ✅ | `test_research_library.py`, `test_parsing.py`; pypdfium2 real; **Docling only stand-in-tested** |
| FR-RES-2 `lit.ask` with page citations | ✅ | real eval through the plugin: 8/8, then 7/8 with one inexact quotation correctly flagged ([results](bench/results-2026-11-05-plugin.md)); synthetic papers only |
| FR-RES-3 jobs: queue, resume, schedule | ✅ | `test_jobs_resume.py` |
| FR-RES-4 review pipeline | ✅ | `evals/litreview_table` with real models through the plugin: 12/12, then 11/12 from the eval's own mistake, on synthetic papers; an earlier run 9/12 led to the two-try rule for excluding; `test_jobs_resume.py` |
| FR-RES-5 citation check | ✅ | `test_citation_check.py`; `evals/citation_existence` tests the checker, `evals/pdf_qa` real answers; DOIs are only checked for form |
| FR-RES-6 CSL formatting, APA/IEEE | ✅ | `test_csl.py`, `test_cite.py`; real citeproc-js and pandoc in CI |
| FR-RES-7 Zotero | 🧪 | `test_zotero.py` (fake local API) |
| FR-RES-8 arXiv | 🧪 | `test_sources.py`, `test_online.py` (synthetic responses) |
| FR-RES-9 Semantic Scholar, OpenAlex, PubMed, Crossref | 🧪 | as above |
| FR-RES-10 research tools over MCP | ✅ | `test_mcp_builtins.py`, `test_online.py` (`lit_find`) |
| FR-RES-11 multi-agent YAML workflows | 🧪 | `test_workflow.py` (real jobs, audit and policy; scripted model); not yet run with a real model |
| FR-RES-12 PaperQA2 spike | ✅ | ADR-0014 |
| FR-RES-13 PaperQA2 deep engine | ✅ | `test_paperqa_guard.py`, `test_deep_engine.py`; real eval through the plugin: 8/8 twice, though wrong working summaries still reach some answers |

