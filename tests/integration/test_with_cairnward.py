"""The package under a real Cairnward: real `serve`, sandbox, gateway, egress and audit log, with a
scripted model. Skipped unless `cairnward` is on PATH (or CAIRNWARD_BIN names it) and the sandbox
is installed. This is what the fake core in conftest.py stands in for."""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.pdf import make_pdf

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
BIN = os.environ.get("CAIRNWARD_BIN") or shutil.which("cairnward")
ANSWER = "Six gardeners reported pesticide use [1]."


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


class Ollama(BaseHTTPRequestHandler):
    """Ollama's real reply formats."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a: Any) -> None:
        pass

    def _send(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._send({"models": [{"name": "m"}, {"name": "e"}]})

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/api/embed"):
            inputs = req["input"] if isinstance(req["input"], list) else [req["input"]]
            self._send({"embeddings": [[float(len(t) % 7), 1.0, 0.5] for t in inputs],
                        "prompt_eval_count": 3})  # fmt: skip
            return
        self._send({"done": True, "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 2,
                    "model": req["model"], "message": {"role": "assistant", "content": ANSWER}})  # fmt: skip


class Stack:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.env = {**os.environ, "CAIRNWARD_CONFIG_DIR": str(tmp / "cfg"),
                    "CAIRNWARD_DATA_DIR": str(tmp / "data"), "CAIRNWARD_STATE_DIR": str(tmp / "st")}  # fmt: skip
        self.env["PATH"] = f"{Path(BIN or '').parent}{os.pathsep}{self.env['PATH']}"
        for name in ("CAIRNWARD_PLUGIN_KEY", "CAIRNWARD_GATEWAY_URL", "CAIRNWARD_PLUGIN_DATA"):
            self.env.pop(name, None)
        self.serve: subprocess.Popen[str] | None = None

    def cw(self, *args: str, timeout: float = 240) -> subprocess.CompletedProcess[str]:
        return subprocess.run([BIN or "", *args], env=self.env, capture_output=True, text=True,
                              timeout=timeout, check=False)  # fmt: skip

    def research(self, *args: str, timeout: float = 240) -> subprocess.CompletedProcess[str]:
        exe = Path(sys.prefix) / "bin" / "cairnward-research"
        return subprocess.run([str(exe), *args], env=self.env, capture_output=True, text=True,
                              timeout=timeout, check=False)  # fmt: skip

    def start(self) -> None:
        self.serve = subprocess.Popen([BIN or "", "serve"], env=self.env, text=True,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        status = self.cw("status", "--wait", "60")
        assert "core isolated" in status.stdout, status.stdout + status.stderr

    def stop(self) -> None:
        if self.serve:
            self.serve.terminate()
            self.serve.wait(20)
            self.serve = None


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    if BIN is None:
        pytest.skip("cairnward isn't on PATH (CAIRNWARD_BIN)")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s = Stack(tmp_path)
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "cairnward.toml").write_text(
        f"[server]\ngateway_port = {free_port()}\ndashboard_port = {free_port()}\n"
        f'egress_port = {free_port()}\n[privacy]\npreset = "balanced"\napprovals = "off"\n'
    )
    (tmp_path / "cfg" / "backends.toml").write_text(
        f'[backends.local-ollama]\ndriver = "ollama"\nurl = "http://127.0.0.1:{srv.server_address[1]}"\n'
        '[roles.main]\nbackend = "local-ollama"\nmodel = "m"\n'
        '[roles.fast]\nbackend = "local-ollama"\nmodel = "m"\n'
        '[roles.embed]\nbackend = "local-ollama"\nmodel = "e"\n'
    )
    if "sandbox" not in s.cw("sandbox", "status").stdout.lower():  # pragma: no cover
        pytest.skip("no sandbox")
    yield s
    s.stop()
    srv.shutdown()


def test_library_ask_and_tools_under_the_contract(stack: Stack, tmp_path: Path) -> None:
    add = stack.research("install-plugin", "--yes")
    assert add.returncode == 0, add.stdout + add.stderr
    stack.start()
    verified = stack.cw("plugin", "verify", "research", "--env", "litreview-offline")
    assert verified.returncode == 0, verified.stdout + verified.stderr
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "bees.pdf").write_bytes(make_pdf(
        [[f"Line {i}: pesticide use was reported by 6 of the 42 gardeners." for i in range(25)]],
        title="Bees"))  # fmt: skip
    created = stack.research("library", "create", "bees", str(papers))
    assert created.returncode == 0, created.stdout + created.stderr
    indexed = stack.research("library", "index", "bees")
    assert indexed.returncode == 0 and "1 added" in indexed.stdout, indexed.stdout + indexed.stderr
    asked = stack.research("library", "ask", "bees", "How many gardeners used pesticides?",
                           "--json")  # fmt: skip
    assert asked.returncode == 0, asked.stdout + asked.stderr
    answer = json.loads(asked.stdout)
    assert answer["sources"][0]["file"] == "bees.pdf" and "Six" in answer["text"]

    # the PDFs' folder was added for the plugin, and the server reads settings when it starts
    stack.stop()
    stack.start()
    approved = stack.cw("mcp", "approve", "research", "--yes")
    assert approved.returncode == 0, approved.stdout + approved.stderr
    key = stack.cw("client", "add", "tester").stdout.splitlines()[1]
    msgs: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "research__lit_ask",
                    "arguments": {"question": "How many gardeners used pesticides?"}}},
    ]  # fmt: skip
    shim = subprocess.run([BIN or "", "mcp", "--env", "litreview-offline", "--key", key],
                          env=stack.env, text=True, timeout=240, capture_output=True, check=False,
                          input="".join(json.dumps(m) + "\n" for m in msgs))  # fmt: skip
    replies = [json.loads(x) for x in shim.stdout.splitlines()]
    assert len(replies) == 3, shim.stdout + shim.stderr
    assert "research__lit_review_start" in [t["name"] for t in replies[1]["result"]["tools"]]
    assert "Six gardeners" in replies[2]["result"]["content"][0]["text"], replies[2]
    stack.stop()
    time.sleep(1)
    log = stack.cw("audit", "log", "--json", "--last", "400").stdout
    records = [json.loads(x) for x in log.splitlines()]
    start = next(r for r in records if r["action"] == "mcp.start" and r["target"] == "research")
    assert start["details"]["sandboxed"] is True
    assert any(r["action"] == "model.call" and str(r.get("client", "")).startswith("plugin-research")
               for r in records)  # fmt: skip
    assert "gardeners" not in log  # digests only


def test_a_locked_library_through_the_key_service(stack: Stack, tmp_path: Path) -> None:
    assert stack.research("install-plugin", "--yes").returncode == 0
    stack.start()
    assert stack.cw("plugin", "verify", "research", "--env", "litreview-offline").returncode == 0
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "a.pdf").write_bytes(make_pdf([["confidential line"] * 25], title="A"))
    assert stack.research("library", "create", "a", str(papers)).returncode == 0
    assert stack.research("library", "index", "a").returncode == 0
    # the passphrase prompt reads a terminal: this checks the service the same call uses
    code = """
import os, sys
from cairnward_research.gateway import KeyService
from cairnward_research.runtime import load
keys = KeyService(load())
key = keys.lock_item("library:a", "correct horse battery")
assert keys.open_item("library:a", "correct horse battery") == key
try:
    keys.open_item("library:a", "wrong passphrase")
except Exception as exc:
    print("refused", exc)
keys.remove_item("library:a")
print("ok", keys.is_locked("library:a"))
"""
    script = tmp_path / "data" / "mcp" / "research" / "probe.py"
    script.write_text(code)
    python = Path(sys.prefix) / "bin" / "python"
    out = stack.cw("plugin", "run", "--env", "litreview-offline", "research", "--", str(python),
                   str(script))  # fmt: skip
    assert "refused" in out.stdout and "ok False" in out.stdout, out.stdout + out.stderr
