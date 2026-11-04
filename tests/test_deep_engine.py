"""PaperQA2 in research jobs (FR-RES-13 + FR-RES-3): the worker runs in the plugin's sandbox with
the plugin's key, and its answer is mapped and checked."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from cairnward_research import Research
from cairnward_research.engines import paperqa
from cairnward_research.engines.deep import DeepEngine
from tests.fakes.pdf import HashEmbedder, make_pdf

WORKER = """
import json, os, sys
spec = json.load(sys.stdin)
print("noise")
print("RESULT " + json.dumps({"answer": "Sleep helps (sleep pages 1-1).", "contexts": [
    {"name": "sleep pages 1-1", "docname": "sleep", "score": 8, "summary": "s", "text": "t"}],
    "added": 1, "seen_key": os.environ["CAIRNWARD_API_KEY"], "gateway": spec["gateway"]}))
"""


@pytest.fixture
def lib(tmp_path: Path, rt: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "sleep.pdf").write_bytes(make_pdf([["Sleep helps memory."] * 20], title="Sleep"))
    with Research.open(rt.paths) as r:
        r.create("thesis", papers, "litreview-offline")
    with Research.open(rt.paths) as r:
        asyncio.run(r.index("thesis", HashEmbedder(model_name="cw/litreview-offline:embed")))
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER)
    monkeypatch.setattr(paperqa, "WORKER", worker)
    monkeypatch.setattr(paperqa, "python", lambda paths: Path(sys.executable))
    return rt


async def test_a_job_asks_through_the_worker(lib: Any) -> None:
    answer = await DeepEngine(lib).ask("thesis", "Does sleep help?")
    assert answer.text == "Sleep helps [1]." and answer.sources[0].file == "sleep.pdf"
    assert answer.model.startswith("paperqa")


def test_the_worker_gets_the_plugins_key_and_gateway(lib: Any) -> None:
    prep = paperqa.prepare(lib, "thesis")
    result = paperqa.execute(lib, prep, "q?")
    assert result["seen_key"] == lib.key and result["gateway"] == lib.gateway
    assert prep.models == {"main": "litreview-offline:high", "fast": "litreview-offline:low",
                           "embed": "litreview-offline:embed"}  # fmt: skip


def test_index_stays_in_the_plugins_folder(lib: Any) -> None:
    prep = paperqa.prepare(lib, "thesis")
    assert prep.work.is_relative_to(lib.paths.data_dir)
    assert prep.work.stat().st_mode & 0o077 == 0 or os.name == "nt"


def test_a_failing_worker_is_reported(lib: Any, tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    worker = tmp_path / "bad.py"
    worker.write_text('print("ERROR " + __import__("json").dumps({"error": "boom"}))')
    monkeypatch.setattr(paperqa, "WORKER", worker)
    with pytest.raises(paperqa.EngineError, match="boom"):
        paperqa.ask(lib, "thesis", "q?")
