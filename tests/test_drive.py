"""Drive mirror (FR-SYNC-2) with a stand-in `rclone` on PATH: a local folder plays the
remote, and every rclone command is logged, so the test can check that Cairnward only
reads from the remote (config dump, lsjson, copy remote -> local)."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from cairnward_research import Research, drive
from cairnward_research.cli import main
from cairnward_research.runtime import Paths

FAKE_RCLONE = r"""#!{python}
import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["FAKE_DRIVE"])
with open(os.environ["FAKE_RCLONE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:] + ["proxy=" + os.environ.get("HTTPS_PROXY", "")]) + "\n")
args = sys.argv[1:]
if args[:2] == ["config", "dump"]:
    print(json.dumps({"gdrive": {"type": "drive", "scope": os.environ.get("FAKE_SCOPE", "")}}))
elif args[0] == "lsjson":
    base = root / args[1].split(":", 1)[1]
    print(json.dumps([{"Path": p.relative_to(base).as_posix(), "Size": p.stat().st_size}
                      for p in base.rglob("*") if p.is_file()]))
elif args[0] == "copy":
    base, dest = root / args[1].split(":", 1)[1], Path(args[2])
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            t = dest / p.relative_to(base)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, t)
else:
    sys.exit(f"unexpected rclone command {args}")
"""


@pytest.fixture
def fake_rclone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if sys.platform == "win32":
        pytest.skip("POSIX script on PATH")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "rclone"
    exe.write_text(FAKE_RCLONE.replace("{python}", sys.executable))
    exe.chmod(0o755)
    remote = tmp_path / "remote" / "Papers"
    (remote / "sub").mkdir(parents=True)
    (remote / "a.pdf").write_bytes(b"%PDF a")
    (remote / "sub" / "b.pdf").write_bytes(b"%PDF b")
    (remote / "notes.txt").write_text("not a pdf")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DRIVE", str(tmp_path / "remote"))
    monkeypatch.setenv("FAKE_RCLONE_LOG", str(tmp_path / "rclone.log"))
    return remote


def commands(tmp_path: Path) -> list[list[str]]:
    return [json.loads(x) for x in (tmp_path / "rclone.log").read_text().splitlines()]


def test_preview_mirror_prune(fake_rclone: Path, tmp_path: Path) -> None:
    local = tmp_path / "library" / "drive"
    assert drive.check_remote("gdrive:Papers")[0].startswith("remote 'gdrive' can change")
    todo = drive.plan(drive.listing("gdrive:Papers"), local)
    assert todo == {"new": ["a.pdf", "sub/b.pdf"], "changed": [], "unchanged": [], "gone": []}
    drive.mirror("gdrive:Papers", local)
    assert (local / "sub" / "b.pdf").read_bytes() == b"%PDF b" and not (
        local / "notes.txt"
    ).exists()
    (fake_rclone / "a.pdf").write_bytes(b"%PDF a, revised")
    (fake_rclone / "sub" / "b.pdf").unlink()
    again = drive.mirror("gdrive:Papers", local)
    assert again["changed"] == ["a.pdf"] and again["gone"] == ["sub/b.pdf"]
    assert (local / "sub" / "b.pdf").exists()  # kept unless --prune
    drive.mirror("gdrive:Papers", local, prune=True)
    assert not (local / "sub" / "b.pdf").exists()
    # only reading: config dump, lsjson, and copy FROM the remote TO the library
    for cmd in commands(tmp_path):
        assert cmd[0] in ("config", "lsjson", "copy") and cmd[-1] == "proxy="
        if cmd[0] == "copy":
            assert cmd[1] == "gdrive:Papers" and cmd[2] == str(local)
    with pytest.raises(drive.DriveError, match="no rclone remote 'other'"):
        drive.check_remote("other:x")


def test_cli_follows_the_policy(fake_rclone: Path, tmp_path: Path,
                                monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    monkeypatch.setenv("FAKE_SCOPE", "drive.readonly")
    paths = Paths(tmp_path / "data", tmp_path / "state")
    monkeypatch.setenv("CAIRNWARD_PLUGIN_DATA", str(paths.data_dir))
    # as `cairnward plugin helper` would: the program runs with the proxy set
    helper = tmp_path / "bin" / "cairnward"
    helper.write_text('#!/bin/sh\nshift 6\nHTTPS_PROXY=http://cw:token@127.0.0.1:9 exec "$@"\n')
    helper.chmod(0o755)
    folder = tmp_path / "library"
    folder.mkdir()
    with Research.open(paths) as r:
        r.create("online", folder, "scratch")
    base = ["library", "drive"]
    assert main([*base, "online", "--remote", "gdrive:Papers", "--preview"]) == 0
    assert "would copy 2 new" in capsys.readouterr().out and not (folder / "drive").exists()
    assert main([*base, "online", "--remote", "gdrive:Papers", "--no-index"]) == 0
    assert (folder / "drive" / "a.pdf").exists()
    assert all(c[-1] == "proxy=http://cw:token@127.0.0.1:9" for c in commands(tmp_path))
    shutil.rmtree(folder / "drive")
