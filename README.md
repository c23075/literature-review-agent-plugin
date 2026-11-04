# cairnward-research

Literature libraries and reviews, as a plugin for [Cairnward](https://github.com/c23075/possessed-incantation), a local privacy gateway.

- **Ask a folder of PDFs.** Answers cite the page. Quotations are checked against the papers.
- **Review overnight.** Screening, notes per paper, a comparison table and APA or IEEE references, as a resumable job.
- **Find papers,** when you turn it on: OpenAlex, Semantic Scholar, arXiv, Crossref and PubMed.

**What's been tested:** every result so far uses short synthetic papers on one CPU-only machine, so
it says little about real papers. See [what's known to go wrong](#known-problems).

## Install
You need Cairnward running. Then:

```bash
uv tool install .
```

```bash
cairnward-research install-plugin
```

Restart `cairnward serve`, then:

```bash
cairnward plugin verify research
```

```bash
cairnward mcp approve research
```

If you used `cairnward library` before research moved here, bring your libraries over once:

```bash
cairnward-research import
```

## Use it
```bash
cairnward-research library create thesis ~/papers --env litreview-offline
```

```bash
cairnward-research library index thesis
```

```bash
cairnward-research library ask thesis "How far did the glacier retreat?"
```

A review, started tonight:

```bash
cairnward-research research review thesis --question "Does sleep affect working memory?" --at 23:30
```

Scheduled jobs run while the plugin's server is up, or with `cairnward-research jobs run --forever`. Check on them with `cairnward-research jobs list`.

Check a draft's quotations and references:

```bash
cairnward-research library check thesis draft.md
```

Format references:

```bash
cairnward-research cite references.json --style apa
```

Chat clients and agents get the same through MCP: `research__lit_search`, `research__lit_ask`, `research__lit_find`, `research__lit_review_start`, `research__lit_job_status` and `research__lit_job_result`. The [skill](skills/literature-review/SKILL.md) describes the workflow.

## Settings
`research.toml`, in the plugin's data folder (`~/.local/share/cairnward/mcp/research/`):

```toml
citation_engine = "auto"      # auto, builtin, citeproc-js or pandoc
default_effort = "high"
# grobid_url = "http://127.0.0.1:8070"

[sources]                     # online sources per environment: off unless listed
litreview-online = ["openalex", "semantic-scholar", "arxiv", "crossref", "pubmed"]
```

GROBID and Zotero need a direct local connection: set them here before `install-plugin`, and Cairnward shows the exception when you add the plugin.

Optional engines stay out of this package's dependencies and install into the data folder:

```bash
cairnward-research research engine install paperqa
```

`docling` and `citeproc-js` install the same way.

## How it's protected
Commands and the MCP server run in Cairnward's sandbox, with only the gateway reachable. Model calls and outside requests go through Cairnward, which checks, scans and audits them. Details are in Cairnward's `docs/plugins.md`.

A few things run outside the sandbox: installing engines, mirroring Drive through rclone (its traffic still goes through egress), and moving downloaded PDFs into your library folder.

An open-access PDF on a host not in the plugin's `fetch_hosts` is refused. To allow one, add the host to `mcp.toml` and restart Cairnward.

## Without Cairnward
```bash
export CAIRNWARD_RESEARCH_BASE_URL=http://127.0.0.1:11434/v1
```

```bash
cairnward-research --standalone library index thesis
```

Set `chat_model`, `fast_model` and `embed_model` in `research.toml`.

**None of the protections above apply** in this mode: no sandbox, no redaction, no audit, and PDFs are parsed with your full rights.

## Known problems
- **PaperQA2 can misdescribe a source.** Its fast model can write a wrong summary, and the main model repeats it as what the paper says. A prompt fix stopped one form of this, but others still pass the checks ([results](docs/bench/results-2026-11-04-paperqa-reruns.md)). Prefer the default engine until you've tried it on your own papers.
- **Checks catch quotations, not paraphrase.** A false claim without quotation marks isn't detected.
- **Locking** doesn't cover your source PDFs, and a library is plain text while unlocked.
- **Prompt injection from papers** can still mislead a model. See `evals/injection`.

## Development
```bash
uv sync
```

```bash
uv run ruff check . && uv run mypy && uv run pytest -q
```

`tests/integration` runs under a real Cairnward: set `CAIRNWARD_BIN` to its `cairnward` program, with the sandbox installed. Other tests use a stand-in for its services, over real HTTP.

The evals need a running Cairnward and real models: `evals/pdf_qa`, `evals/litreview_table`, `evals/citation_existence` and `evals/injection`.
