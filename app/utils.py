
from __future__ import annotations
import os, subprocess
from contextlib import contextmanager
from typing import Iterator

def run(cmd: list[str], cwd: str | None = None, env: dict | None = None):
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out, err

@contextmanager
def span(name: str, **attrs) -> Iterator[None]:
    # no-op span placeholder; add OpenTelemetry if desired
    try:
        yield
    finally:
        pass

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
