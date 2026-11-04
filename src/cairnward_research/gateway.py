"""The services: every call the plugin makes outside its sandbox goes through here."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from cairnward_research.runtime import Runtime

LONG = httpx.Timeout(3600, connect=30)


class ServiceError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


def client(rt: Runtime, *, timeout: Any = LONG) -> httpx.AsyncClient:
    if not rt.gateway:
        raise ServiceError(0, "not running under Cairnward: start this with `cairnward plugin "
                              "run research`, or set CAIRNWARD_RESEARCH_BASE_URL for standalone "
                              "use")  # fmt: skip
    # trust_env stays on: inside the sandbox its proxy is the only way to the gateway
    return httpx.AsyncClient(base_url=rt.gateway, timeout=timeout,
                             headers={"Authorization": f"Bearer {rt.key or ''}"})  # fmt: skip


def sync_client(rt: Runtime) -> httpx.Client:
    if not rt.gateway:
        raise ServiceError(0, "not running under Cairnward")
    return httpx.Client(base_url=rt.gateway, timeout=60,
                        headers={"Authorization": f"Bearer {rt.key or ''}"})  # fmt: skip


def detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", err))[:300]
        return str(body.get("detail", body))[:300]
    return str(body)[:300]


class FetchTransport(httpx.AsyncBaseTransport):
    """An httpx transport over the fetch service, so the academic-API code doesn't change: each
    request, and each redirect hop, is one checked and audited request in the core."""

    def __init__(self, rt: Runtime, timeout_s: float = 60) -> None:
        self.rt, self.timeout_s = rt, timeout_s

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "content-length", "connection")}  # fmt: skip
        async with client(self.rt, timeout=self.timeout_s + 30) as c:
            resp = await c.post("/cairnward/fetch", json={
                "method": request.method, "url": str(request.url), "headers": headers,
                "timeout_s": self.timeout_s,
                "body_b64": base64.b64encode(body).decode() if body else None})  # fmt: skip
        if resp.status_code != 200:
            raise httpx.TransportError(f"Cairnward refused it: {detail(resp)}")
        out = resp.json()
        drop = {"content-length", "transfer-encoding", "connection"}
        kept = [(k, v) for k, v in out["headers"].items() if k.lower() not in drop]
        data = base64.b64decode(out["body_b64"])
        return httpx.Response(out["status"], headers=kept, stream=httpx.ByteStream(data),
                              request=request)  # fmt: skip


class KeyService:
    """A locked library's key, kept by the core with the conversations' keys, so the recovery
    key covers it too. The plugin gets the key only with the passphrase."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def _call(self, op: str, item: str, secret: str | None = None) -> dict[str, Any]:
        with sync_client(self.rt) as c:
            resp = c.post("/cairnward/item-keys", json={"op": op, "item": item, "secret": secret})
        if resp.status_code != 200:
            raise ServiceError(resp.status_code, detail(resp))
        out: dict[str, Any] = resp.json()
        return out

    def is_locked(self, item: str) -> bool:
        return bool(self._call("status", item)["locked"])

    def lock_item(self, item: str, secret: str) -> bytes:
        return base64.b64decode(self._call("lock", item, secret)["key_b64"])

    def open_item(self, item: str, secret: str) -> bytes:
        return base64.b64decode(self._call("open", item, secret)["key_b64"])

    def remove_item(self, item: str) -> None:
        self._call("remove", item)

    def recover(self, item: str, identity: str, secret: str) -> None:
        self._call("recover", item, f"{identity}\n{secret}")


async def save_artifact(rt: Runtime, path: str, content: bytes, message: str | None = None) -> str:
    async with client(rt, timeout=60) as c:
        resp = await c.post("/cairnward/artifacts", json={
            "path": path, "content_b64": base64.b64encode(content).decode(),
            "message": message})  # fmt: skip
    if resp.status_code != 200:
        raise ServiceError(resp.status_code, detail(resp))
    return str(resp.json()["rev"])
