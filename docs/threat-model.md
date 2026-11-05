# Threat model

What's specific to this plugin. The sandbox, the services and the rules a plugin runs under are in
[Cairnward's threat model](https://github.com/c23075/possessed-incantation/blob/main/docs/threat-model.md)
(T-29 to T-32). Numbers are kept from there, where these began.

| # | Category | Threat | Controls | Spec | Req |
|---|---|---|---|---|---|
| T-24 | Info disclosure | The research library is plain text in `research.db` unless locked; locking a conversation doesn't cover a library it used | Owner-only data folder; encrypted in backups; `cairnward-research library lock` seals its text, embeddings and metadata. Residual: the source PDFs stay in your folder, a library is plain while unlocked, and older backups hold it | §4.6 | FR-RES-1 |
| T-25 | Elevation of privilege | A crafted PDF exploits a third-party engine, or PaperQA2's cached index is altered | Since ADR-0017, parsing and these workers run in the research plugin's sandbox, not the core. PaperQA2 and Docling have their own environment; PaperQA2 refuses settings that don't point at the gateway; Presidio runs inside the core's sandbox with no network; PaperQA2's index is JSON in the plugin's owner-only data folder, which agent runs and other MCP servers can't reach, so altering it can change answers but can't run code (it was a pickle until I27) | §4.6 | FR-RES-13, FR-RED-2 |

| # | Category | Threat | Controls |
|---|---|---|---|
| P-01 | Linking | Queries to academic APIs/search engines from one IP build a research profile | Network opt-in; allow-listed hosts; results cached locally for a week; optional proxy/Tor-friendly egress setting (Phase 2) |

**Prompt injection from papers:** a planted instruction can still reach an answer (I23 in
[status.md](status.md)). `evals/injection` runs a corpus on the real model. An answer has no tools,
and Cairnward gates plugin output.

**Wrong answers:** quotation and reference checks, answers cited to the page, and evals for invented
citations reduce this. They don't remove it (I20).
