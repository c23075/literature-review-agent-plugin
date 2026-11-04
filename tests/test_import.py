"""Bringing libraries over from before the split: a real database from the old layout."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from cairnward_research import GatewayEmbedder, Research, cli
from cairnward_research.db import make_engine
from cairnward_research.runtime import Paths
from tests.fakes.pdf import make_pdf


async def old_data(tmp_path: Path, rt: Any) -> Path:
    """Made by this code in a folder laid out as Cairnward's data folder was."""
    old = tmp_path / "old"
    paths = Paths(old, old / "state")
    folder = tmp_path / "papers"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(make_pdf([["sleep helps memory"] * 20], title="A"))
    with Research.open(paths) as r:
        r.create("thesis", folder, "litreview-offline")
        await r.index("thesis", GatewayEmbedder(rt, environment="litreview-offline"))
    (old / "library-locks").mkdir()
    (old / "library-locks" / "other.age").write_bytes(b"sealed")
    (old / "jobs" / "j1").mkdir(parents=True)
    (old / "jobs" / "j1" / "job.json").write_text("{}")
    make_engine(old / "research.db").dispose()
    return old


async def test_import_copies_and_keeps_the_originals(tmp_path: Path, cli_env: Any, core: Any,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    rt = cli_env
    old = await old_data(tmp_path, rt)
    allowed: list[Path] = []
    monkeypatch.setattr(cli, "_allow_folder", lambda f: allowed.append(f) or 0)
    assert cli.main(["import", "--from", str(old)]) == 0
    data = rt.paths.data_dir
    assert (data / "library-locks" / "other.age").read_bytes() == b"sealed"
    assert (data / "jobs" / "j1" / "job.json").exists()
    assert (old / "research.db").exists()
    assert allowed == [tmp_path / "papers"]
    with Research.open(rt.paths) as r:
        hits = await r.search(
            "thesis", "sleep", GatewayEmbedder(rt, environment="litreview-offline"), k=1
        )
    assert hits and "sleep" in hits[0].text
    shutil.rmtree(old)  # nothing depends on the old folder now
    capsys.readouterr()
    assert cli.main(["import", "--from", str(old)]) == 1  # refuses to overwrite
    assert "already has" in capsys.readouterr().err


def test_nothing_to_import(
    tmp_path: Path, cli_env: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["import", "--from", str(tmp_path / "nowhere")]) == 1
    assert "no research.db" in capsys.readouterr().err
