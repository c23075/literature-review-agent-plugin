"""What the CLI and the MCP server share: the job runner and library indexing."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cairnward_research import Research, gateway
from cairnward_research.ask import run_ask
from cairnward_research.embedder import GatewayEmbedder
from cairnward_research.engines.deep import DeepEngine
from cairnward_research.jobs import JobRunner, JobStore
from cairnward_research.llm import GatewayChat
from cairnward_research.parsing import hooks
from cairnward_research.runtime import Runtime


def chat_for(rt: Runtime) -> Any:
    def make(library: str, effort: str | None = None, actor: str | None = None) -> GatewayChat:
        with Research.open(rt.paths) as research:
            env = research.get(library).environment
        return GatewayChat(rt, environment=env, effort=effort,
                           purpose="workflow" if actor else "review")  # fmt: skip

    return make


def index_for(rt: Runtime) -> Any:
    async def index(library: str, files: list[str] | None, actor: str) -> dict[str, Any]:
        with Research.open(rt.paths) as research:
            env = research.get(library).environment
            embedder = GatewayEmbedder(rt, environment=env)
            parse_many, enrich = hooks(rt, library, env)
            report = await research.index(library, embedder, only=files, parse_many=parse_many,
                                          enrich=enrich)  # fmt: skip
        fields = ("added", "updated", "unchanged", "no_text", "failed", "missing", "chunks",
                  "seconds")  # fmt: skip
        return {k: getattr(report, k) for k in fields}

    return index


def runner(rt: Runtime, log: Any = lambda m: None) -> JobRunner:
    async def ask(library: str, question: str, **kw: Any) -> Any:
        kw.pop("actor", None)
        return await run_ask(rt, library, question, **kw)

    async def artifact(path: str, content: bytes, message: str) -> None:
        if rt.under_contract:
            await gateway.save_artifact(rt, path, content, message)

    def accept(job: Any) -> bool:
        """A key works in one environment: other jobs wait for a runner there."""
        if rt.environment is None:
            return True
        try:
            with Research.open(rt.paths) as research:
                return bool(research.get(job.params["library"]).environment == rt.environment)
        except (KeyError, ValueError):
            return False

    return JobRunner(JobStore(rt.paths.data_dir), research=lambda: Research.open(rt.paths),
                     ask=ask, chat_for=chat_for(rt), artifact=artifact, log=log,
                     deep=DeepEngine(rt), index=index_for(rt), paths=rt.paths,
                     cite_engine=rt.settings.citation_engine,
                     accept=accept)  # fmt: skip


@contextmanager
def runner_lock(data_dir: Path, environment: str | None) -> Iterator[bool]:
    """Only one process runs an environment's jobs at a time (its key works only there); True
    if this one got the turn."""
    path = data_dir / f"jobs-{environment or 'standalone'}.lock"
    with path.open("w") as f:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
