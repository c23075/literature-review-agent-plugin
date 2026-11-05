"""The plugin brings its own environments, since Cairnward doesn't ship them."""

import tomllib
from pathlib import Path

from cairnward_research.cli import ENVIRONMENTS, _write_environments


def test_environments_are_written_once_and_yours_are_kept(tmp_path: Path) -> None:
    folder = tmp_path / "environments"
    folder.mkdir()
    (folder / "litreview-online.toml").write_text('[privacy]\nnetwork = "off"\n')
    assert _write_environments(tmp_path) == ["litreview-offline"]
    assert "off" in (folder / "litreview-online.toml").read_text()
    assert _write_environments(tmp_path) == []


def test_environments_keep_their_protections() -> None:
    offline = tomllib.loads(ENVIRONMENTS["litreview-offline"])["privacy"]
    assert offline == {"network": "off", "hosted_backends": "deny"}
    online = tomllib.loads(ENVIRONMENTS["litreview-online"])["privacy"]
    assert online["network"] == "ask" and "api.openalex.org" in online["network_allow_hosts"]
