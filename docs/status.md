# Project status

Last updated 2026-11-05. This is the owner's view of the research plugin. Cairnward, which it runs
under, has [its own status page](https://github.com/c23075/possessed-incantation/blob/main/docs/status.md).
Requirement by requirement, see [requirements-status.md](requirements-status.md).

**It isn't production ready.** Every result so far uses short synthetic papers, so its accuracy on
real ones is unknown.

## What needs you
Choose about 20 research papers on one question: about 14 to keep and 6 to reject. This measures how
many relevant papers screening loses. It can be done later. (Its number in Cairnward's list was A2.)

## Issues
Numbers are kept from Cairnward's list, where these began.

| # | Issue | State |
|---|---|---|
| I6 | A research library is plain while unlocked, its source PDFs are never encrypted, and it has no timed unlock (T-24) | Accepted |
| I12 | Only the built-in APA and IEEE citation styles work until pandoc or citeproc-js is installed | Your choice |
| I17 | Question q5's failure in the first eval. I22 could be the cause, but those answers weren't kept | Unexplained |
| I20 | PaperQA2's fast model can write wrong summaries, and the main model repeats them as what a source says. The prompt change stopped the false "explicitly states" claims in the latest runs, but q3 still mentions a date no paper gives (`docs/bench/results-2026-11-05-plugin.md`) | Open, partly fixed |
| I21 | PaperQA2's refusals in other words weren't recognised. Wider detection now finds them, but can also mark a partial answer as a refusal | Fixed, with that risk |
| I22 | The check failed a correct "Six" on q5 because it looked for "6" | Fixed |
| I23 | A paper's planted instruction can still reach an answer. On the real model, one got its code into 2 of 4 lean runs, one of them with the new rule in place. The bad citation it asked for was flagged; an instruction without one wouldn't be | Open: limited, not preventable. An answer has no tools, and plugin output is gated |
| I24 | The research repository's first Windows run found a Linux-only lock, a test checking POSIX file modes, and line endings breaking the citation files' hash check | Fixed in its PR 1 |
| I26 | A paper can end a workflow step with no notes when reasoning uses its token limit. It's now reported and later steps are told, but nothing retries it | Open |
| I27 | PaperQA2's index was a pickle, so changing the file could run code in the worker. Its signature protected little once the key sat in the same folder as the index | Fixed: stored as JSON. Tested with the real paper-qa and a scripted model, not yet a real model. Existing indexes are rebuilt once |

## Testing still to do
- [ ] Real papers: accuracy, and how many relevant papers screening loses
- [x] Evals on a real model through the plugin, 2026-11-05: answers, review and injection all ran, with the failures explained in `docs/bench`
- [x] Workflows on a real model, synthetic papers, 2026-11-05: found a bug, now fixed. The fix has only run against a stand-in
- [ ] Workflows on real papers
- [x] Locking a library through a live isolated server, 2026-11-05
- [ ] Screening's disagreement path
- [x] Injection test corpus: written and run on the real model (I23). Six cases, so it shows that an attack works, not that the others are safe

### Tested only against a stand-in
- [ ] Academic sources: arXiv, Semantic Scholar, OpenAlex, PubMed, Crossref
- [ ] Zotero, Docling, GROBID
- [ ] Drive through real rclone
