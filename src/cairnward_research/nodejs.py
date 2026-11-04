"""Finding Node, for citeproc-js."""

from __future__ import annotations

import re
import shutil
import subprocess


def node_version(node: str = "node") -> tuple[int, int] | None:
    exe = shutil.which(node)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                             check=True).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None
