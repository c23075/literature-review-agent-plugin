"""Engine locks shipped in the repository: Presidio's covers every package and the spaCy
model wheel with hashes; a shipped lock is preferred over resolving; a lock recorded on
a machine can be exported for committing."""

import re
from pathlib import Path

import pytest

from cairnward_research.engines import locks


def _requirements(text: str) -> list[str]:
    """Each requirement with its continuation lines joined."""
    return [r.strip() for r in re.sub(r"\\\n\s*", " ", text).splitlines()
            if r.strip() and not r.lstrip().startswith("#")]  # fmt: skip


def test_shipped_and_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locks, "LOCK_DIR", tmp_path / "locks")
    assert locks.shipped("docling") is None
    recorded = tmp_path / "requirements.lock.txt"
    with pytest.raises(FileNotFoundError):
        locks.export("docling", recorded)
    recorded.write_text("docling==2.140.0 --hash=sha256:00\n")
    dest = locks.export("docling", recorded)
    assert dest.name == f"docling-{locks.platform_tag()}.txt"
    assert locks.shipped("docling") == dest
    (tmp_path / "locks" / "docling.txt").write_text("x")
    assert locks.shipped("docling") == dest  # a platform-specific lock comes first
