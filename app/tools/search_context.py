from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import List

from strands import tool
from app import runtime

log = logging.getLogger(__name__)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    log.addHandler(_h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

_DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_CONTEXT_MAX_RESULTS", "20"))
_DEFAULT_MAX_CHARS = int(os.getenv("SEARCH_CONTEXT_MAX_CHARS", "8000"))
_DEFAULT_CONTEXT_LINES = int(os.getenv("SEARCH_CONTEXT_LINES", "2"))

@tool(name="search_context", description="Search repository code and return snippets for additional context.")
def search_context(
    query: str,
    repo_dir: str | None = None,
    max_results: int = _DEFAULT_MAX_RESULTS,
    max_chars: int = _DEFAULT_MAX_CHARS,
    context_lines: int = _DEFAULT_CONTEXT_LINES,
) -> dict:
    """Search repo for ``query`` and return code snippets.

    Uses ripgrep to locate matching lines, then reads surrounding context from disk.
    Output is capped by ``max_results`` and ``max_chars`` to avoid oversized payloads.
    """
    
    if repo_dir is None:
        ws = runtime.get_workspace()
        repo_dir = (ws or {}).get("repo_dir") if ws else None
    if not repo_dir:
        raise ValueError("search_context: repo_dir not provided and no workspace set")
    if not query.strip():
        return {"query": query, "results": [], "truncated": False}

    cmd = ["rg", "--json", query, repo_dir]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    snippets: List[str] = []
    total = 0
    truncated = False

    return_code: int | None = None
    stderr_output = ""

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if len(snippets) >= max_results or total >= max_chars:
                truncated = True
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            path = event["data"]["path"]["text"]
            line_no = event["data"]["line_number"]
            abs_path = os.path.join(repo_dir, path)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
            except OSError as ex:
                log.warning("search_context: failed to read %s: %s", abs_path, ex)
                continue
            start = max(0, line_no - 1 - context_lines)
            end = min(len(lines), line_no + context_lines)
            snippet_lines = [f"# {path}"]
            for idx in range(start, end):
                prefix = ">" if idx == line_no - 1 else " "
                snippet_lines.append(f"{prefix}{idx+1:>4}: {lines[idx].rstrip()}")
            snippet = "\n".join(snippet_lines)
            if total + len(snippet) > max_chars:
                snippet = snippet[: max(0, max_chars - total)]
                truncated = True
            snippets.append(snippet)
            total += len(snippet)
            if truncated:
                break
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass
        try:
            return_code = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            return_code = proc.wait()
        if proc.stderr:
            try:
                stderr_output = proc.stderr.read().strip()
            except OSError as exc:  # pragma: no cover - unlikely but defensive
                stderr_output = f"<failed to read stderr: {exc}>"
        if stderr_output:
            log.warning("search_context: ripgrep stderr: %s", stderr_output)
        if return_code not in (0, None):
            log.warning("search_context: ripgrep exited with code %s", return_code)

    return {"query": query, "results": snippets, "truncated": truncated}
