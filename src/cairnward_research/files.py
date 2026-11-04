"""Packing, atomic writes and removing plaintext, for locking a library."""

from __future__ import annotations

import io
import os
import shutil
import stat
import tarfile
from pathlib import Path

SEALED = "sealed.age"


def _pack(repo: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for child in sorted(repo.iterdir()):
            if child.name != SEALED:
                tar.add(child, arcname=child.name)
    return buf.getvalue()


def _unpack(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        tar.extractall(dest, filter="data")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())  # needs a writable file on Windows
    if os.name != "nt":
        tmp.chmod(0o600)
    tmp.replace(path)


def _remove_plaintext(repo: Path) -> None:
    """Everything in a repository's folder except the sealed bundle."""
    if repo.is_dir():
        for child in repo.iterdir():
            if child.name != SEALED:
                remove_tree(child) if child.is_dir() else child.unlink()


def _private_tmp() -> str | None:
    """A memory-backed folder when there is one, so plaintext stays off the disk."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return runtime if runtime and Path(runtime).is_dir() else None


def remove_tree(path: Path) -> None:
    """rmtree that also removes read-only files (git objects on Windows)."""

    def writable_then_retry(func: object, target: str, _exc: object) -> None:
        t = Path(target)
        t.chmod(stat.S_IWRITE)
        if t.is_file():
            t.unlink()
        else:
            t.rmdir()

    shutil.rmtree(path, onexc=writable_then_retry)
