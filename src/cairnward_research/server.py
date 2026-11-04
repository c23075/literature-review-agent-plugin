"""The MCP server: what any chat client or agent gets through Cairnward (ADR-0017). Long reviews
are started and polled; they never run inside one MCP call."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from cairnward_research import Research, __version__, service
from cairnward_research.ask import run_ask
from cairnward_research.embedder import GatewayEmbedder
from cairnward_research.jobs import JobStore, review_job
from cairnward_research.online import Online, OnlineError
from cairnward_research.runtime import DEFAULT_ENVIRONMENT, Runtime, load

STRING = {"type": "string"}
READ_ONLY = types.ToolAnnotations(read_only_hint=True)
# The plugin's definitions are pinned, so they don't change with the libraries you have.
TOOLS = [
    types.Tool(
        name="lit_search",
        description="Search the user's literature library for passages relevant to a question "
        "(vector + keyword search). Returns passages with titles and page numbers; cite them as "
        "[title, p. N].",
        input_schema={"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string", "description": "what to look for"}, "library": STRING,
            "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8}}},
        annotations=READ_ONLY,
    ),
    types.Tool(
        name="lit_ask",
        description="Answer a question from the user's literature library, citing passages by "
        "page. Takes minutes on a CPU. It may answer that the sources don't say.",
        input_schema={"type": "object", "required": ["question"], "properties": {
            "question": STRING, "library": STRING}},
        annotations=READ_ONLY,
    ),
    types.Tool(
        name="lit_find",
        description="Search academic databases online, when turned on for this environment. "
        "Returns records, not full text; the user adds papers to a library themselves.",
        input_schema={"type": "object", "required": ["query"], "properties": {
            "query": STRING, "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            "sources": {"type": "array", "items": STRING}}},
        annotations=READ_ONLY,
    ),
    types.Tool(
        name="lit_review_start",
        description="Start a literature review job: screening, notes per paper with pages, a "
        "comparison table and references. Runs for minutes to hours; returns a job id for "
        "lit_job_status and lit_job_result.",
        input_schema={"type": "object", "required": ["question"], "properties": {
            "question": STRING, "library": STRING, "criteria": STRING,
            "style": {"type": "string", "enum": ["apa", "ieee"]}}},
    ),
    types.Tool(
        name="lit_job_status",
        description="A research job's progress.",
        input_schema={"type": "object", "required": ["job_id"], "properties": {"job_id": STRING}},
        annotations=READ_ONLY,
    ),
    types.Tool(
        name="lit_job_result",
        description="A finished research job's result, as Markdown.",
        input_schema={"type": "object", "required": ["job_id"], "properties": {"job_id": STRING}},
        annotations=READ_ONLY,
    ),
]  # fmt: skip


def _text(text: str, structured: dict[str, Any] | None = None) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                structured_content=structured)  # fmt: skip


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)


class Tools:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.environment = rt.environment or DEFAULT_ENVIRONMENT
        self.runner = service.runner(rt)

    def libraries(self) -> list[str]:
        with contextlib.closing(Research.open(self.rt.paths)) as research:
            return [lib.name for lib, _docs, _chunks in research.list_libraries()
                    if lib.environment == self.environment and lib.embedding_dim
                    and not lib.locked]  # fmt: skip

    def library(self, args: dict[str, Any]) -> str:
        names = self.libraries()
        name = args.get("library") or (names[0] if len(names) == 1 else None)
        if name not in names:
            raise ValueError(f"name one of the libraries here: {', '.join(names) or 'none yet'}")
        return str(name)

    async def call(self, tool: str, args: dict[str, Any]) -> types.CallToolResult:
        handler = getattr(self, f"_{tool}", None)
        if tool not in {t.name for t in TOOLS} or handler is None:
            return _error(f"no tool {tool}")
        try:
            result: types.CallToolResult = await handler(args)
        except (ValueError, OnlineError) as exc:
            return _error(str(exc))
        return result

    async def _lit_search(self, args: dict[str, Any]) -> types.CallToolResult:
        name = self.library(args)
        query = str(args.get("query", "")).strip()
        if len(query) < 3:
            return _error("give a query")
        k = max(1, min(int(args.get("k", 8) or 8), 20))
        research = Research.open(self.rt.paths)
        try:
            hits = await research.search(
                name, query, GatewayEmbedder(self.rt, environment=self.environment), k=k
            )
        finally:
            research.close()
        lines = [f"[{h.title or Path(h.path).name}, {h.pages}] {h.text}" for h in hits]
        return _text("\n\n".join(lines) or "No passages found.", {"passages": [
            {"title": h.title, "file": Path(h.path).name, "pages": h.pages, "text": h.text}
            for h in hits]})  # fmt: skip

    async def _lit_ask(self, args: dict[str, Any]) -> types.CallToolResult:
        name = self.library(args)
        question = str(args.get("question", "")).strip()
        if len(question) < 3:
            return _error("give a question")
        answer = await run_ask(self.rt, name, question)
        return _text(answer.render(), {
            "cannot_answer": answer.cannot_answer, "uncited": answer.uncited,
            "sources": [{"file": s.file, "pages": s.pages} for s in answer.sources]})  # fmt: skip

    async def _lit_find(self, args: dict[str, Any]) -> types.CallToolResult:
        query = str(args.get("query", "")).strip()
        out = await Online(self.rt).search(self.environment, query, sources=args.get("sources"),
                                           limit=min(int(args.get("limit", 10) or 10),
                                                     25))  # fmt: skip
        lines = [f"{r['title']} ({r['year'] or 'n.d.'}) doi:{r['doi'] or '-'}"
                 for r in out["records"]]  # fmt: skip
        failed = [f"{n}: {r['error']}" for n, r in out["sources"].items() if "error" in r]
        text = "\n".join(lines) or "No papers found."
        if failed:
            text += "\n\nSources that failed: " + "; ".join(failed)
        return _text(text, {"records": out["records"]})

    async def _lit_review_start(self, args: dict[str, Any]) -> types.CallToolResult:
        name = self.library(args)
        question = str(args.get("question", "")).strip()
        if len(question) < 3:
            return _error("give a question")
        style = args.get("style") if args.get("style") in ("apa", "ieee") else "apa"
        criteria = str(args.get("criteria") or "").strip()[:4000] or None
        job = review_job(name, question, str(style), criteria=criteria, actor="client")
        self.runner.submit(job)
        return _text(f"Review job {job.id} queued. It indexes the library, screens every paper, "
                     "reads the included ones and writes a synthesis. Check it with "
                     "lit_job_status.", {"job_id": job.id})  # fmt: skip

    def _job(self, args: dict[str, Any]) -> Any:
        store = JobStore(self.rt.paths.data_dir)
        try:
            return store.load(str(args.get("job_id", "")))
        except (OSError, ValueError, KeyError):
            raise ValueError(f"no job {args.get('job_id')}") from None

    async def _lit_job_status(self, args: dict[str, Any]) -> types.CallToolResult:
        summary = self._job(args).summary()
        return _text(json.dumps(summary), summary)

    async def _lit_job_result(self, args: dict[str, Any]) -> types.CallToolResult:
        job = self._job(args)
        path = JobStore(self.rt.paths.data_dir).result_path(job.id)
        if job.status not in ("done", "failed") or not path.exists():
            return _error(f"not finished: {job.status}")
        return _text(path.read_text(encoding="utf-8"))


async def amain() -> None:
    rt = load()
    tools = Tools(rt)

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def call_tool(ctx: Any, params: Any) -> types.CallToolResult:
        return await tools.call(params.name, dict(params.arguments or {}))

    server = Server("cairnward-research", version=__version__, on_list_tools=list_tools,
                    on_call_tool=call_tool)  # fmt: skip

    async def jobs() -> None:
        with service.runner_lock(rt.paths.data_dir, rt.environment) as ours:
            if ours:
                await tools.runner.run_forever()
            else:  # a foreground `jobs run` has the turn; don't wait on it
                await asyncio.Event().wait()

    task = asyncio.create_task(jobs())
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        task.cancel()


def main() -> None:
    anyio.run(amain)
