"""PaperQA2 for research jobs (FR-RES-13 with FR-RES-3): the worker runs in this plugin's
sandbox, so a job only needs a thread to wait in."""

from __future__ import annotations

import asyncio
from typing import Any

from cairnward_research.engines import paperqa
from cairnward_research.runtime import Runtime


class DeepEngine:
    def __init__(self, rt: Runtime):
        self.rt = rt

    async def ask(self, library: str, question: str, *, effort: str | None = None,
                  evidence_k: int = 10, skip_summary: bool = False,
                  actor: str = "cairnward") -> Any:  # fmt: skip
        return await asyncio.to_thread(paperqa.ask, self.rt, library, question, effort=effort,
                                       evidence_k=evidence_k,
                                       skip_summary=skip_summary)  # fmt: skip
