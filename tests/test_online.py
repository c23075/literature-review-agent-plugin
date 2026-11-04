"""Online sources through the core's fetch service, over real HTTP: the academic-API code is the
same, but each request and redirect is a call to the service. What the service itself decides
(policy, redaction, hosts) is tested in Cairnward."""

import asyncio
import base64
from typing import Any

import httpx
import pytest

from cairnward_research.online import Online, OnlineError
from tests.test_sources import PDF, responder


def route_to(transport: httpx.MockTransport) -> Any:
    def origin(body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        req = httpx.Request(body["method"], body["url"], headers=body["headers"],
                            content=base64.b64decode(body["body_b64"] or ""))  # fmt: skip
        resp = transport.handle_request(req)
        resp.read()
        return resp.status_code, dict(resp.headers), resp.content

    return origin


async def test_search_and_fetch_go_through_the_service(rt: Any, core: Any) -> None:
    calls: list[str] = []
    core.origin = route_to(responder(calls))
    o = Online(rt)
    out = await o.search("litreview-online", "sleep and working memory", limit=5)
    assert out["records"] and all("error" not in r for r in out["sources"].values())
    assert core.fetches and all(f["url"].startswith("https://") for f in core.fetches)
    (item,) = await o.fetch("litreview-online", ["10.1111/jsr.99001"])
    assert base64.b64decode(item["pdf_b64"]) == PDF
    assert item["filename"].endswith(".pdf") and item["csl"]["DOI"] == "10.1111/jsr.99001"


async def test_a_refused_host_is_reported_per_source(rt: Any, core: Any) -> None:
    out = await Online(rt).search("litreview-online", "sleep and working memory")
    assert "Cairnward refused" in out["sources"]["openalex"]["error"]


async def test_sources_are_off_unless_turned_on(rt: Any, core: Any) -> None:
    o = Online(rt)
    with pytest.raises(OnlineError, match="online sources are off"):
        await o.search("litreview-offline", "sleep and working memory")
    with pytest.raises(OnlineError, match="unknown source"):
        await o.search("litreview-online", "sleep", sources=["nope"])
    assert not core.fetches
    await asyncio.sleep(0)
