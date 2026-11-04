"""A stand-in for Cairnward's plugin services, over real HTTP: the package's clients open real
sockets here, because mock transports have hidden real bugs (Cairnward's CLAUDE.md)."""

import base64
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from cairnward_research.runtime import ENV_KEY, Paths, Runtime, Settings


@dataclass
class FakeCore:
    """Chat answers, embeddings, the fetch service and item keys, in the gateway's formats."""

    reply: str | Callable[[dict[str, Any]], str] = "I can't answer this from these sources."
    finish_reason: str = "stop"
    context_tokens: int | None = 8192
    thinking: bool = False
    refuse_models: str | None = None
    chats: list[dict[str, Any]] = field(default_factory=list)
    fetches: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    origin: Callable[[dict[str, Any]], tuple[int, dict[str, str], bytes]] | None = None
    keys: dict[str, tuple[str, str]] = field(default_factory=dict)
    url: str = ""

    def answer(self, method: str, path: str, query: str, body: Any) -> tuple[int, Any]:
        if path.endswith("/chat/completions"):
            if self.refuse_models:
                return 403, {"error": {"message": self.refuse_models}}
            self.chats.append(body)
            text = self.reply(body) if callable(self.reply) else self.reply
            return 200, {"model": "fake", "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                         "choices": [{"finish_reason": self.finish_reason,
                                      "message": {"role": "assistant", "content": text}}]}  # fmt: skip
        if path.endswith("/embeddings"):
            if self.refuse_models:
                return 403, {"error": {"message": self.refuse_models}}
            return 200, {"data": [{"index": i, "embedding": _vector(t)}
                                  for i, t in enumerate(body["input"])]}  # fmt: skip
        if path.endswith("/cairnward/model-info"):
            return 200, {"context_tokens": self.context_tokens, "thinking": self.thinking,
                         "subagent_limit": 2, "subagent_parallel": 1}  # fmt: skip
        if path.endswith("/cairnward/fetch"):
            self.fetches.append(body)
            if self.origin is None:
                return 403, {"detail": "not in fetch_hosts"}
            status, headers, data = self.origin(body)
            return 200, {"status": status, "headers": headers, "warning": None,
                         "body_b64": base64.b64encode(data).decode()}  # fmt: skip
        if path.endswith("/cairnward/artifacts"):
            self.artifacts[body["path"]] = base64.b64decode(body["content_b64"])
            return 200, {"rev": "abc"}
        if path.endswith("/cairnward/item-keys"):
            return self._item_key(body)
        return 404, {"detail": f"no {path}"}

    def _item_key(self, body: dict[str, Any]) -> tuple[int, Any]:
        from pyrage import x25519

        op, item, secret = body["op"], body["item"], body.get("secret")
        if op == "status":
            return 200, {"locked": item in self.keys}
        if op == "remove":
            self.keys.pop(item, None)
            return 200, {"ok": True}
        if op == "lock":
            if len(secret or "") < 8:
                return 400, {"detail": "passphrase too short"}
            key = str(x25519.Identity.generate())
            self.keys[item] = (key, secret)
        if item not in self.keys:
            return 400, {"detail": "not locked"}
        key, kept = self.keys[item]
        if op == "recover":
            identity, _, new = secret.partition("\n")
            if identity != "recovery":
                return 400, {"detail": "wrong recovery key"}
            self.keys[item] = (key, new)
            return 200, {"ok": True}
        if kept != secret:
            return 400, {"detail": "wrong passphrase"}
        return 200, {"key_b64": base64.b64encode(key.encode()).decode()}


def _vector(text: str, dim: int = 64) -> list[float]:
    import hashlib

    out = [0.0] * dim
    for word in text.lower().split():
        out[int(hashlib.sha256(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = sum(x * x for x in out) ** 0.5 or 1.0
    return [x / norm for x in out]


@pytest.fixture
def core() -> Iterator[FakeCore]:
    fake = FakeCore()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a: Any) -> None:
            pass

        def _do(self, method: str) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            path, _, query = self.path.partition("?")
            status, body = fake.answer(method, path, query, json.loads(raw) if raw else None)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            self._do("POST")

        def do_GET(self) -> None:
            self._do("GET")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    yield fake
    srv.shutdown()


@pytest.fixture
def rt(tmp_path: Path, core: FakeCore, monkeypatch: pytest.MonkeyPatch) -> Runtime:
    """As the plugin sees itself under Cairnward, with online sources on in litreview-online."""
    monkeypatch.setenv(ENV_KEY, "cw-run-test")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    data = tmp_path / "data"
    data.mkdir()
    return Runtime(Paths(data, data / "state"),
                   Settings(sources={"litreview-online": ["openalex", "semantic-scholar", "arxiv",
                                                          "crossref", "pubmed"]}),
                   core.url, "cw-run-test", "litreview-offline")  # fmt: skip


@pytest.fixture
def cli_env(rt: Runtime, core: FakeCore, monkeypatch: pytest.MonkeyPatch) -> Runtime:
    """The CLI as it runs inside the plugin's sandbox."""
    monkeypatch.setenv("CAIRNWARD_GATEWAY_URL", core.url)
    monkeypatch.setenv("CAIRNWARD_PLUGIN_DATA", str(rt.paths.data_dir))
    monkeypatch.setenv("CAIRNWARD_ENVIRONMENT", "litreview-offline")
    return rt
