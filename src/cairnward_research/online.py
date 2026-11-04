"""Searching online academic sources and fetching open-access PDFs (FR-RES-8/9). Every request
goes through the core's fetch service, which checks it as `net.connect` in the environment,
scans what's sent with redaction, and records a digest in the audit log.

Sources are off unless research.toml turns them on for an environment.
"""

from __future__ import annotations

import base64
from typing import Any

from cairnward_research.gateway import FetchTransport
from cairnward_research.runtime import Runtime
from cairnward_research.sources import SOURCES, Searcher, slug


class OnlineError(Exception):
    pass


def enabled_sources(rt: Runtime, environment: str, wanted: list[str] | None) -> list[str]:
    allowed = list(rt.settings.sources.get(environment, []))
    if not allowed:
        raise OnlineError(f"online sources are off in '{environment}': add\n  [sources]\n  "
                          f"{environment} = [{', '.join(repr(s) for s in SOURCES)}]\nto "
                          f"{rt.paths.data_dir / 'research.toml'}")  # fmt: skip
    if not wanted:
        return allowed
    unknown = [s for s in wanted if s not in SOURCES]
    if unknown:
        raise OnlineError(f"unknown source(s) {', '.join(unknown)}: {', '.join(SOURCES)}")
    off = [s for s in wanted if s not in allowed]
    if off:
        raise OnlineError(f"not enabled in '{environment}': {', '.join(off)}")
    return wanted


class Online:
    def __init__(self, rt: Runtime, *, transport: Any = None) -> None:
        self.rt = rt
        self.transport = transport  # tests: an httpx mock transport

    def _searcher(self) -> Searcher:
        transport = self.transport or (FetchTransport(self.rt) if self.rt.gateway else None)
        return Searcher(self.rt.paths.data_dir / "research_cache", proxy=None, check=None,
                        transport=transport)  # fmt: skip

    async def search(self, environment: str, query: str, *, sources: list[str] | None = None,
                     limit: int = 10) -> dict[str, Any]:  # fmt: skip
        query = query.strip()
        if len(query) < 3:
            raise OnlineError("the query is too short")
        chosen = enabled_sources(self.rt, environment, sources)
        s = self._searcher()
        try:
            out: dict[str, Any] = await s.search(chosen, query, limit=max(1, min(limit, 50)))
        finally:
            await s.aclose()
        return out

    async def fetch(self, environment: str, ids: list[str]) -> list[dict[str, Any]]:
        """For each id (`doi:...`, `arxiv:...` or a DOI): metadata and the open-access PDF."""
        from cairnward_research.sources import SourceError

        enabled_sources(self.rt, environment, None)
        s = self._searcher()
        out: list[dict[str, Any]] = []
        try:
            for ident in ids[:50]:
                try:
                    rec = await s.lookup(ident)
                    pdf = await s.fetch_pdf(rec)
                except SourceError as exc:
                    out.append({"id": ident, "error": str(exc)})
                    continue
                out.append({"id": ident, "title": rec.title, "filename": slug(rec) + ".pdf",
                            "csl": rec.csl(),
                            "pdf_b64": base64.b64encode(pdf).decode()})  # fmt: skip
        finally:
            await s.aclose()
        return out
