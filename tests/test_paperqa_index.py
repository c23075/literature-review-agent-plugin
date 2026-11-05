"""PaperQA2's cached index (FR-RES-13): JSON, never pickle, so loading it can't run code.

The stand-in tests run everywhere. The last test uses the real, pinned paper-qa and is skipped
unless CAIRNWARD_PAPERQA_VENV points at a virtual environment that has it
(`cairnward-research research engine install paperqa` makes one, under the data folder's
`engines/paperqa/venv`)."""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, model_validator

from cairnward_research.engines import paperqa
from cairnward_research.runtime import Paths
from tests.fakes.pdf import make_pdf
from tests.test_paperqa_guard import worker

VENV = os.environ.get("CAIRNWARD_PAPERQA_VENV")


class FakeDoc(BaseModel):
    docname: str


class FakeDetails(FakeDoc):
    """Like DocDetails: given a plain Doc's fields, it renames the document."""

    @model_validator(mode="after")
    def _rename(self) -> "FakeDetails":
        self.docname = "unknownauthorsUnknownyearunknowntitle"
        return self


class FakeDocs(BaseModel):
    """Stands in for PaperQA2's Docs: documents typed as a union that pydantic resolves the
    wrong way, and a search index the cache leaves out."""

    docs: dict[str, FakeDetails | FakeDoc] = {}
    texts: list[str] = []
    texts_index: list[str] = []


CLASSES: dict[str, Any] = {"FakeDoc": FakeDoc, "FakeDetails": FakeDetails}


def saved(tmp_path: Path) -> tuple[Any, Path]:
    w, cache = worker(), tmp_path / "index.json"
    docs = FakeDocs(docs={"k1": FakeDoc(docname="walker2024")}, texts=["a", "b"],
                    texts_index=["built"])  # fmt: skip
    assert type(docs.docs["k1"]) is FakeDoc
    w.save_cache(cache, docs, "1")
    return w, cache


def test_round_trip_keeps_each_document_and_leaves_out_the_search_index(tmp_path: Path) -> None:
    assert worker().load_cache(tmp_path / "index.json", FakeDocs, CLASSES, "1") is None
    w, cache = saved(tmp_path)
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert stored["doc_types"] == {"k1": "FakeDoc"} and "texts_index" not in stored["docs"]
    loaded = w.load_cache(cache, FakeDocs, CLASSES, "1")
    assert loaded.texts == ["a", "b"] and loaded.texts_index == []
    assert type(loaded.docs["k1"]) is FakeDoc and loaded.docs["k1"].docname == "walker2024"
    # left to pydantic, the document would come back renamed
    assert FakeDocs.model_validate(stored["docs"]).docs["k1"].docname != "walker2024"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "change",
    [
        lambda d: "not json",
        lambda d: "[1, 2]",
        lambda d: json.dumps({**d, "format": 2}),  # a later format
        lambda d: json.dumps({**d, "paperqa": "0.9"}),  # another PaperQA2 version
        lambda d: json.dumps({**d, "doc_types": {"k1": "Unknown"}}),
        lambda d: json.dumps({k: v for k, v in d.items() if k != "doc_types"}),
        lambda d: json.dumps({**d, "doc_types": {"k1": "FakeDetails"}}),  # would rename it
        lambda d: json.dumps({**d, "docs": {**d["docs"], "texts": "not a list"}}),
        lambda d: "\x80\x04\x95",  # the old pickled index's first bytes, under the new name
    ],
)
def test_an_unusable_index_is_rebuilt(tmp_path: Path, change: Any,
                                      capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    w, cache = saved(tmp_path)
    cache.write_text(change(json.loads(cache.read_text(encoding="utf-8"))), encoding="utf-8")
    assert w.load_cache(cache, FakeDocs, CLASSES, "1") is None
    assert "rebuilding it" in capsys.readouterr().err


def test_the_pickled_index_and_its_key_are_removed(tmp_path: Path) -> None:
    paths = Paths(tmp_path / "d", tmp_path / "d" / "state")
    root = paperqa.cache_dir(paths.data_dir)
    a, b = root / "a", root / "b"
    for lib in (a, b):
        lib.mkdir(parents=True)
        (lib / "index.pkl").write_bytes(b"old")
        (lib / "index.pkl.sig").write_text("sig")
    (lib / paperqa.INDEX).write_text("{}")
    paths.state_dir.mkdir(parents=True)
    key = paths.state_dir / paperqa.OLD_KEY
    key.write_text("00")
    paperqa.remove_old_cache(paths, a)
    assert not (a / "index.pkl").exists() and not (a / "index.pkl.sig").exists()
    assert key.exists()  # b still has a pickled index
    paperqa.remove_old_cache(paths, b)
    assert not key.exists() and (b / paperqa.INDEX).exists()


ROUND_TRIP = r"""
import asyncio, importlib.util, json, sys
from pathlib import Path

worker_path, pdf, cache = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("pqa_worker", worker_path)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

from paperqa import Doc, DocDetails, Docs, Settings, __version__
from paperqa.llms import SparseEmbeddingModel
from paperqa.settings import ParsingSettings

EMBEDDED = [0]


class Counting(SparseEmbeddingModel):  # local, no network: counts the texts it embeds
    async def embed_documents(self, texts):
        EMBEDDED[0] += len(texts)
        return await super().embed_documents(texts)


async def main():
    model = Counting()
    settings = Settings(embedding="sparse",
                        parsing=ParsingSettings(use_doc_details=False, multimodal=0))
    docs = Docs()
    await docs.aadd(pdf, citation="Walker, Sleep and memory, 2024", docname="walker2024",
                    settings=settings, embedding_model=model)
    w.save_cache(cache, docs, __version__)
    classes = {"Doc": Doc, "DocDetails": DocDetails}
    loaded = w.load_cache(cache, Docs, classes, __version__)
    assert loaded is not None, "the index didn't load"
    EMBEDDED[0] = 0
    want = await docs.retrieve_texts("sleep and working memory", k=2, settings=settings,
                                     embedding_model=model)
    original_calls, EMBEDDED[0] = EMBEDDED[0], 0
    got = await loaded.retrieve_texts("sleep and working memory", k=2, settings=settings,
                                      embedding_model=model)
    print(json.dumps({
        "texts": len(docs.texts),
        "same_texts": [t.text for t in loaded.texts] == [t.text for t in docs.texts],
        "same_embeddings": [t.embedding for t in loaded.texts] == [t.embedding for t in docs.texts],
        "docnames": sorted(d.docname for d in loaded.docs.values()),
        "known": sorted(loaded.docnames),
        "doc_type": ([type(d).__name__ for d in loaded.docs.values()]
                     == [type(d).__name__ for d in docs.docs.values()]
                     and [type(t.doc).__name__ for t in loaded.texts]
                     == [type(t.doc).__name__ for t in docs.texts]),
        "same_hits": [t.name for t in got] == [t.name for t in want] and len(got) > 0,
        "embedded_on_search": EMBEDDED[0], "embedded_on_search_before": original_calls,
        "other_version": w.load_cache(cache, Docs, classes, "0") is None,
    }))


asyncio.run(main())
"""


@pytest.mark.skipif(not VENV, reason="needs CAIRNWARD_PAPERQA_VENV (a venv with paper-qa)")
def test_real_paperqa_index_round_trip(tmp_path: Path) -> None:
    """With the pinned paper-qa: what's saved loads back the same, and searching the loaded
    index embeds only the question, not the papers again."""
    assert VENV
    python = Path(VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pdf = tmp_path / "walker2024.pdf"
    pdf.write_bytes(make_pdf([
        ["Sleep and working memory in older adults.", "Longer sleep went with better",
         "working memory scores in the 2024 cohort."],
        ["Caffeine late in the day shortened sleep.", "Napping did not change the scores."],
    ]))  # fmt: skip
    script = tmp_path / "round_trip.py"
    script.write_text(ROUND_TRIP, encoding="utf-8")
    res = subprocess.run([str(python), "-I", str(script), str(paperqa.WORKER), str(pdf),
                          str(tmp_path / paperqa.INDEX)], capture_output=True, text=True,
                         timeout=600, cwd=tmp_path, check=False)  # fmt: skip
    assert res.returncode == 0, res.stderr[-3000:]
    out: dict[str, Any] = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["texts"] > 0 and out["same_texts"] and out["same_embeddings"], out
    # the worker matches papers by these names: a renamed one would be added and embedded again
    assert out["docnames"] == out["known"] == ["walker2024"], out
    assert out["doc_type"] and out["same_hits"], out
    # the original index embeds only the question too; the loaded one must not re-embed papers
    assert out["embedded_on_search"] == out["embedded_on_search_before"] == 1, out
    assert out["other_version"], out


class ScriptedModels(BaseHTTPRequestHandler):
    """An OpenAI-compatible server standing in for the gateway: hashed embeddings and canned
    answers. Records the texts it was asked to embed."""

    embedded: list[str] = []  # noqa: RUF012

    def log_message(self, *a: Any) -> None:
        pass

    def send(self, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/embeddings"):
            texts = req["input"] if isinstance(req["input"], list) else [req["input"]]
            ScriptedModels.embedded += texts
            data = [{"object": "embedding", "index": i,
                     "embedding": [b / 255 for b in hashlib.sha256(t.encode()).digest()] * 8}
                    for i, t in enumerate(texts)]  # fmt: skip
            self.send({"object": "list", "data": data, "model": req["model"],
                       "usage": {"prompt_tokens": 10, "total_tokens": 10}})  # fmt: skip
            return
        prompt = "\n".join(str(m.get("content", "")) for m in req["messages"])
        if "relevance_score" in prompt:
            text = json.dumps({"summary": "Longer sleep went with better working memory.",
                               "relevance_score": 8})  # fmt: skip
        else:
            key = re.search(r"\b(pqac-[0-9a-f]{8})", prompt)  # PaperQA2's context ids
            text = f"Longer sleep improved working memory ({key.group(1) if key else 'none'})."
        self.send({"id": "x", "object": "chat.completion", "created": 0, "model": req["model"],
                   "choices": [{"index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": text}}],
                   "usage": {"prompt_tokens": 50, "completion_tokens": 20,
                             "total_tokens": 70}})  # fmt: skip


@pytest.fixture
def models() -> Iterator[str]:
    ScriptedModels.embedded = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModels)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


@pytest.mark.skipif(not VENV, reason="needs CAIRNWARD_PAPERQA_VENV (a venv with paper-qa)")
def test_real_worker_reuses_its_json_index(tmp_path: Path, models: str) -> None:
    """The worker itself, with the pinned paper-qa and a scripted model server: the first
    question adds the paper and writes index.json; the second loads it, adds nothing and
    embeds only the question."""
    assert VENV
    python = Path(VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pdf = tmp_path / "walker2024.pdf"
    lines = [
        "Sleep and working memory in older adults.",
        "Longer sleep went with better working memory scores.",
    ]
    pdf.write_bytes(make_pdf([lines]))
    cache = tmp_path / paperqa.INDEX
    spec = {"gateway": models, "models": {"main": "e:medium", "fast": "e:low", "embed": "e:embed"},
            "papers": [{"path": str(pdf), "docname": "walker2024", "title": "Walker 2024"}],
            "cache": str(cache), "evidence_k": 2, "skip_summary": False}  # fmt: skip
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "NO_PROXY": "*",
           "no_proxy": "*", "CAIRNWARD_API_KEY": "cw-run-test"}  # fmt: skip

    def ask(question: str) -> dict[str, Any]:
        res = subprocess.run([str(python), "-I", str(paperqa.WORKER)],
                             input=json.dumps({**spec, "question": question}), env=env,
                             capture_output=True, text=True, timeout=600, cwd=tmp_path,
                             check=False)  # fmt: skip
        line = next((x for x in res.stdout.splitlines() if x.startswith(("RESULT ", "ERROR "))),
                    "")  # fmt: skip
        assert line.startswith("RESULT "), (res.stdout[-2000:], res.stderr[-3000:])
        out: dict[str, Any] = json.loads(line[7:])
        return out

    first = ask("Does sleep help working memory?")
    assert first["added"] == 1 and first["contexts"] and cache.exists()
    assert json.loads(cache.read_text(encoding="utf-8"))["format"] == 1
    papers_embedded = len(ScriptedModels.embedded)
    ScriptedModels.embedded = []
    second = ask("What about naps?")
    assert second["added"] == 0 and second["contexts"], second
    assert ScriptedModels.embedded == ["What about naps?"], ScriptedModels.embedded
    assert papers_embedded > 1  # the first run embedded the paper as well as its question


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
