# Handoff, 2026-11-05

Working notes for the next session. Design is in [design.md](design.md), requirement by requirement
in [requirements-status.md](requirements-status.md), and real results in [bench](bench/). Issue
numbers (I20, I23) and action numbers are from Cairnward's `docs/status.md`.

## State
- Moved out of Cairnward under its ADR-0017, and runs as a plugin under contract version 1. The
  repository is `literature-review-agent-plugin`; the package and command are `cairnward-research`.
  The local clone is `../cairnward-research`, and it needs a Cairnward with the plugin contract
  (`main` after its PR 22).
- `main` passes CI on Linux and Windows (run 41935583415). The first Windows runs found a Linux-only
  lock, a test checking POSIX file modes, and `.gitattributes` naming Cairnward's old path. All are
  fixed. This shows the suite runs on Windows, not that the `msvcrt` lock has met a real second
  process: the test takes it twice from one process.
- The owner's real data hasn't moved here. `cairnward-research import` has only run in tests.

## Next
1. With the owner: real papers (about 20: 14 to keep, 6 to reject), then import their data with a
   backup taken first.

## Tested on 2026-11-05
On Linux: 163 passed, 4 skipped (2 pandoc, 2 integration without `CAIRNWARD_BIN`). The integration
tests pass against a real server and sandbox with a scripted model.

On the real model through the plugin, on synthetic papers ([results](bench/results-2026-11-05-plugin.md)):
lean 8/8 then 7/8, PaperQA2 8/8 twice, review 12/12 then 11/12, injection 17/18 on lean with the rule
and 5/6 on PaperQA2. Each failure is explained there.

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run mypy --platform win32   # catches Linux-only modules without a Windows machine
uv run pytest -q
```

The integration tests and evals need Cairnward: set `CAIRNWARD_BIN`, and `CAIRNWARD_SRT` for the
sandbox. For real evals, install from wheels on a separate test server, since editing the source
changes the plugin's digest. After updating, run `cairnward plugin pin research`.

## Open issues
- **I23, injection:** the `system` case still gets a planted code into some lean answers. Only an
  instruction that also asks for a bad citation gets flagged. Answers have no tools, and Cairnward
  gates plugin output.
- **I20, PaperQA2:** wrong working summaries still reach answers (q3's 1990 date). One q3 run took
  1,401 s against about 300 s, which wasn't investigated.
- **Never run for real:** the academic APIs, Zotero, Docling, GROBID, Drive through rclone, workflows
  on a real model.
- **Accuracy on real papers is unknown.** Every result uses short synthetic ones.
- Native Windows has no sandbox, so Windows CI shows the code runs there, not that the plugin's
  protections apply. Cairnward's route for Windows is WSL2, which has never run for real.
