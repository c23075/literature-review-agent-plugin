"""Embeddings for the research library, through the gateway."""

from __future__ import annotations

from typing import Protocol

from cairnward_research import gateway
from cairnward_research.runtime import Runtime


class EmbeddingDenied(Exception):
    pass


class Embedder(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class GatewayEmbedder:
    def __init__(self, rt: Runtime, *, environment: str, batch_size: int = 16):
        self.rt, self.environment, self.batch_size = rt, environment, batch_size
        self.model_name = rt.embed_model(environment)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with gateway.client(self.rt) as c:
            for i in range(0, len(texts), self.batch_size):
                resp = await c.post("/embeddings", json={
                    "model": self.model_name, "input": texts[i : i + self.batch_size]})  # fmt: skip
                if resp.status_code != 200:
                    raise EmbeddingDenied(gateway.detail(resp))
                rows = sorted(resp.json()["data"], key=lambda r: r["index"])
                out += [r["embedding"] for r in rows]
        return out
