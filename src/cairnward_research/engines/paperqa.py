"""PaperQA2 as an optional "deep" engine (ADR-0014, FR-RES-13).

- Installed on request into its own virtual environment in the data folder, from a
  hash-pinned requirements file (`cairnward-research research engine install paperqa`); none of
  its 78 dependencies enter Cairnward's core.
- Each question runs `paperqa_worker.py` with that environment's Python, inside the plugin's
  own sandbox (a nested one isn't possible), with the plugin's key. Every model call it makes
  is a gateway call: policy-checked, queued, audited.
- The worker refuses to start unless every model setting points at the gateway and
  online lookups and image enrichment are off (guard()).
- Its answer is mapped to Cairnward's Answer: PaperQA2's citation keys become [n] with
  file and pages; quotations are checked against the library like the lean pipeline's.

The worker keeps PaperQA2's index (its own chunks and embeddings) in the plugin's data folder,
at `engines/paperqa-index/<library>/`; it is rebuilt when the models change.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairnward_research.runtime import Paths, Runtime

HERE = Path(__file__).parent
WORKER = HERE / "paperqa_worker.py"
REQUIREMENTS = HERE / "paperqa-requirements.txt"
_NAME = re.compile(r"^(?P<doc>.+?) pages (?P<start>\d+)(?:-(?P<end>\d+))?$")
# The model doesn't always use PaperQA2's set phrase. An opening "the context does not ..." can
# also start a partial answer; that only silences the "cites no passage" warning.
_DECLINES = re.compile(
    r"can(?:not|'t| not) answer|cannot be answered|impossible to determine"
    r"|^\s*the context (?:does not|doesn't|provides no)",
    re.IGNORECASE,
)


class EngineError(Exception):
    pass


def engine_dir(paths: Paths) -> Path:
    return paths.data_dir / "engines" / "paperqa"


INDEX = "index.json"  # PaperQA2's chunks and embeddings for one library


def cache_dir(data_dir: Path) -> Path:
    """The engine's working data: its own index of your papers. Owner-only."""
    return data_dir / "engines" / "paperqa-index"


# Left by versions that cached the index with pickle (and signed it): never read now.
OLD_CACHE_FILES = ("index.pkl", "index.pkl.sig", "index.tmp", "index.sig.tmp")
OLD_KEY = "paperqa-cache.key"


def remove_old_cache(paths: Paths, work: Path) -> None:
    """Delete a library's pickled index and, once no library has one, the key that signed it."""
    for name in OLD_CACHE_FILES:
        (work / name).unlink(missing_ok=True)
    root = cache_dir(paths.data_dir)
    if not any(root.glob("*/index.pkl")):
        (paths.state_dir / OLD_KEY).unlink(missing_ok=True)


def python(paths: Paths) -> Path | None:
    exe = engine_dir(paths) / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return exe if exe.exists() else None


def install(paths: Paths, log: Any = print) -> Path:
    """A fresh virtual environment with the pinned, hash-checked PaperQA2."""
    root = engine_dir(paths)
    root.mkdir(parents=True, exist_ok=True)
    venv = root / "venv"
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "--quiet", "--python", "3.12", str(venv)], check=True)
        subprocess.run([uv, "pip", "install", "--quiet", "--require-hashes", "-r",
                        str(REQUIREMENTS), "--python", str(venv)], check=True)  # fmt: skip
    else:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        exe = python(paths)
        if exe is None:
            raise EngineError("the virtual environment wasn't created")
        subprocess.run([str(exe), "-m", "pip", "install", "--quiet", "--require-hashes",
                        "-r", str(REQUIREMENTS)], check=True)  # fmt: skip
    exe = python(paths)
    if exe is None:
        raise EngineError("PaperQA2 didn't install")
    log(f"PaperQA2 installed in {venv}")
    return exe


def _slug(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "", text)[:24] or "paper"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}{n}", n + 1
    taken.add(name)
    return name


def to_answer(question: str, library: str, result: dict[str, Any],
              papers: dict[str, dict[str, Any]], rows: list[Any]) -> Any:  # fmt: skip
    """PaperQA2's answer as Cairnward's Answer: citation keys -> [n] with file and pages."""
    from cairnward_research.ask import Answer, Source
    from cairnward_research.check import _find, quotations

    text = str(result.get("answer") or "").strip()
    answer = Answer(question=question, library=library, text=text,
                    passages=len(result.get("contexts", [])))  # fmt: skip
    names = sorted(
        {c["name"] for c in result.get("contexts", []) if c.get("score", 0) > 0},
        key=len,
        reverse=True,
    )  # longest first, so "x pages 2-3" beats "x pages 2"
    found = sorted((text.find(n), n) for n in names if n in text)  # first mention first
    numbers = {name: i for i, (_pos, name) in enumerate(found, 1)}
    for name in names:  # longest first, so "x pages 2-3" isn't cut by "x pages 2"
        if name in numbers:
            text = text.replace(name, f"[{numbers[name]}]")
    for name, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        m = _NAME.match(name)
        doc = papers.get(m.group("doc") if m else "", {})
        pages = (m.group("start") if not m.group("end") or m.group("end") == m.group("start")
                 else f"{m.group('start')}-{m.group('end')}") if m else "?"  # fmt: skip
        answer.sources.append(Source(n, doc.get("title", name), doc.get("file", name), pages,
                                     int(doc.get("document_id", 0)), 0))  # fmt: skip
    text = re.sub(
        r"\((\[\d+\](?:,\s*\[\d+\])*)\)",
        lambda mm: "[" + ", ".join(re.findall(r"\d+", mm.group(1))) + "]",
        text,
    )
    answer.text = text
    answer.cannot_answer = bool(_DECLINES.search(text.replace("\u2019", "'")))
    answer.uncited = not answer.sources
    for quote, _cited in quotations(text):
        if _find(quote, rows) is None:
            short = quote if len(quote) <= 80 else quote[:77] + "..."
            answer.quote_problems.append(f'"{short}" was not found in the papers')
    return answer


@dataclass
class Prepared:
    """What a question needs: the library's papers as PaperQA2 documents, its chunks
    (for quotation checks), the models, and the engine's working folder."""

    library: str
    environment: str
    papers: dict[str, dict[str, Any]]
    rows: list[Any]
    models: dict[str, str]
    work: Path


def prepare(cfg: Runtime, library: str, effort: str | None = None, *,
            create_work: bool = True) -> Prepared:  # fmt: skip
    """create_work=False: only what's needed to map an answer (the isolated core can't
    write the cache folder; the process that runs the worker prepares it)."""
    from cairnward_research import Research

    if python(cfg.paths) is None:
        raise EngineError(
            "PaperQA2 isn't installed: cairnward-research research engine install paperqa"
        )
    with Research.open(cfg.paths) as research:
        lib = research.get(library)
        docs = [d for d in research.documents(library) if d.status == "indexed"]
        rows = research.chunk_rows(library)
    taken: set[str] = set()
    papers: dict[str, dict[str, Any]] = {}
    for d in docs:
        name = _slug(Path(d.path).stem, taken)
        papers[name] = {"path": str(lib.folder / d.path), "docname": name,
                        "title": d.title or Path(d.path).stem, "file": Path(d.path).name,
                        "document_id": d.id}  # fmt: skip
    env_name = lib.environment
    main_effort = effort or cfg.settings.default_effort
    models = {"main": f"{env_name}:{main_effort}", "fast": f"{env_name}:low",
              "embed": f"{env_name}:embed"}  # fmt: skip
    work = cache_dir(cfg.paths.data_dir) / re.sub(r"[^A-Za-z0-9._-]", "_", library)
    if not create_work:
        return Prepared(library, env_name, papers, rows, models, work)
    for d in (work, work / "home", work / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        for d in (cache_dir(cfg.paths.data_dir), work):
            d.chmod(0o700)
    remove_old_cache(cfg.paths, work)
    meta = work / "models.json"
    if meta.exists() and json.loads(meta.read_text()) != models:
        (work / INDEX).unlink(missing_ok=True)  # embeddings from other models
    meta.write_text(json.dumps(models))
    return Prepared(library, env_name, papers, rows, models, work)


def execute(cfg: Runtime, prep: Prepared, question: str, *, evidence_k: int = 10,
            skip_summary: bool = False) -> dict[str, Any]:  # fmt: skip
    """Run the worker once; its raw result."""
    exe = python(cfg.paths)
    if exe is None:
        raise EngineError("PaperQA2 isn't installed: cairnward-research research engine install "
                          "paperqa")  # fmt: skip
    if not cfg.gateway:
        raise EngineError("PaperQA2 needs Cairnward's gateway")
    work = prep.work
    spec = {"gateway": cfg.gateway, "models": prep.models,
            "papers": list(prep.papers.values()), "question": question,
            "cache": str(work / INDEX), "evidence_k": evidence_k,
            "skip_summary": skip_summary}  # fmt: skip
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ", "HTTP_PROXY", "HTTPS_PROXY",
                                      "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy",
                                      "NODE_EXTRA_CA_CERTS") if k in os.environ}  # fmt: skip
    env.update(HOME=str(work / "home"), TMPDIR=str(work / "tmp"), CAIRNWARD_API_KEY=cfg.key or "",
               NO_PROXY="")  # fmt: skip
    code, out = _run([str(exe), "-I", str(WORKER)], spec, env, work)
    line = next((x for x in reversed(out.splitlines()) if x.startswith(("RESULT ", "ERROR "))), "")
    if not line.startswith("RESULT "):
        detail = json.loads(line[6:])["error"] if line.startswith("ERROR ") else (
            f"the worker stopped (exit {code}); see {work / 'worker.log'}")  # fmt: skip
        raise EngineError(detail)
    result: dict[str, Any] = json.loads(line[7:])
    return result


def finish(prep: Prepared, question: str, result: dict[str, Any], seconds: float) -> Any:
    answer = to_answer(question, prep.library, result, prep.papers, prep.rows)
    answer.seconds = seconds
    answer.model = f"paperqa ({prep.models['main']})"
    return answer


def ask(cfg: Runtime, library: str, question: str, *, effort: str | None = None,
        evidence_k: int = 10, skip_summary: bool = False) -> Any:  # fmt: skip
    prep = prepare(cfg, library, effort)
    started = time.monotonic()
    result = execute(cfg, prep, question, evidence_k=evidence_k, skip_summary=skip_summary)
    return finish(prep, question, result, time.monotonic() - started)


def _run(argv: list[str], spec: dict[str, Any], env: dict[str, str], work: Path) -> tuple[int, str]:
    with (work / "worker.log").open("w", encoding="utf-8") as errlog:
        res = subprocess.run(argv, input=json.dumps(spec), capture_output=False,
                             stdout=subprocess.PIPE, stderr=errlog, text=True, env=env,
                             cwd=work, timeout=6 * 3600, check=False)  # fmt: skip
    return res.returncode, res.stdout
