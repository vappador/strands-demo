# app/code_tools.py
from __future__ import annotations

import json
import logging
import os
from typing import List

from pydantic import ValidationError,BaseModel
from strands import tool, ToolContext

# Import the canonical models from app.models (do NOT re-declare here)
from app.models import (
    Requirement,
    BuildSpec,
    FileEdit,
    ChangePlan,
    format_validation_errors,
)
from app.runners import DockerRunner

log = logging.getLogger("code_tools")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    log.addHandler(_h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


# --------------------------- helpers ---------------------------

_SKIP_DIR_NAMES = {".git", ".venv", ".mypy_cache", ".pytest_cache", "node_modules", "dist", "build", ".idea", ".vscode"}
_INCLUDE_FILE_SUFFIXES = (".py", ".ts", ".js", ".java", ".md", ".yml", ".yaml", ".toml", ".json", ".xml", ".gradle")

def _is_hidden_or_skip_dir(path_parts: List[str]) -> bool:
    for p in path_parts:
        if p in _SKIP_DIR_NAMES or p.startswith("."):
            return True
    return False

def _scan_repo(repo_dir: str, max_files: int = 250) -> str:
    """
    Return a newline-separated inventory of (relative) repo files, filtered for signal.
    """
    out: List[str] = []
    for root, _dirs, files in os.walk(repo_dir):
        parts = os.path.relpath(root, repo_dir).split(os.sep)
        if parts == ["."]:
            parts = []
        if _is_hidden_or_skip_dir(parts):
            continue
        for f in files:
            if f.endswith(_INCLUDE_FILE_SUFFIXES):
                rel = os.path.relpath(os.path.join(root, f), repo_dir)
                out.append(rel)
                if len(out) >= max_files:
                    return "\n".join(out)
    return "\n".join(out)

def _safe_join(base: str, *paths: str) -> str:
    """
    Join and ensure the final path stays under base (prevent path traversal).
    """
    candidate = os.path.abspath(os.path.join(base, *paths))
    base_abs = os.path.abspath(base)
    if not candidate.startswith(base_abs + os.sep) and candidate != base_abs:
        raise ValueError(f"Refusing to write outside repo: {candidate}")
    return candidate

def _ensure_trailing_newline(s: str) -> str:
    return s if s.endswith("\n") else s + "\n"


# --------------------------- tools -----------------------------

@tool(context=True, name="plan_changes", description="Summarize repo & plan edits for the requirement.")
def plan_changes(tool_context: ToolContext, req: Requirement, repo_dir: str) -> ChangePlan:
    """
    Ask the LLM to produce a concise change plan based on the requirement and a repo inventory.
    Returns a ChangePlan (summary + touched_files).
    """
    inventory = _scan_repo(repo_dir)
    prompt = f"""
You are a senior engineer. Given this requirement, output a concise plan.

REQUIREMENT
- TITLE: {req.title}
- ID: {req.id}
- LANGUAGE: {req.language}
- CODE INSTRUCTION:
{req.codegen.description}

REPO INVENTORY (paths):
{inventory}

Return strictly JSON conforming to this Pydantic model:
ChangePlan: {{
  "summary": "string",
  "touched_files": ["relative/path", ...]
}}
"""
    try:
        return tool_context.agent.structured_output(ChangePlan, prompt)
    except ValidationError as exc:
        errors = format_validation_errors(exc) if 'format_validation_errors' in globals() else exc.errors()
        # Provide a compact, machine-readable error object
        raise RuntimeError(json.dumps({"error": "ChangePlanValidationError", "details": errors}, ensure_ascii=False))


@tool(context=True, name="generate_changes", description="Generate concrete file edits for the requirement.")
def generate_changes(tool_context: ToolContext, req: Requirement, plan: ChangePlan, repo_dir: str) -> List[FileEdit]:
    """
    Ask the LLM for concrete edits. Supports actions: create | modify | delete.
    """
    schema_hint = (
        "Return a JSON object with an 'edits' array: "
        '{"edits":[{"action":"create|modify|delete","path":"relative/path","content":"string-or-empty"}]}'
    )
    test_hints = "\n".join(f"- {x}" for x in req.codegen.test_expectations) if req.codegen.test_expectations else "- (none)"
    prompt = f"""
You will propose precise file edits to implement the requirement.

Rules:
- {schema_hint}
- 'path' must be relative to repo root. No absolute paths. No traversal outside the repo.
- Use 'delete' for file removals (content can be empty string).
- Prefer minimal, surgical changes.
- Include unit tests aligning with these expectations:
{test_hints}

Context:
- REQ ID: {req.id}
- TITLE: {req.title}
- LANGUAGE: {req.language}
- PLAN SUMMARY: {plan.summary}
- TOUCH LIST: {plan.touched_files}
- REPO ROOT: {repo_dir}

Only return JSON. No prose.
"""
    # A tiny wrapper struct for the provider to emit proper JSON schema
    class _FileEditListModel(BaseModel):
        edits: List[FileEdit]  # reuse canonical FileEdit from app.models

    try:
        result = tool_context.agent.structured_output(_FileEditListModel, prompt)
    except ValidationError as exc:
        errors = format_validation_errors(exc) if 'format_validation_errors' in globals() else exc.errors()
        raise RuntimeError(json.dumps({"error": "FileEditListValidationError", "details": errors}, ensure_ascii=False))

    # Defensive trimming: normalize paths & ensure allowed actions
    cleaned: List[FileEdit] = []
    for e in result.edits:
        act = e.action.lower().strip()
        if act not in {"create", "modify", "delete"}:
            log.warning("Dropping unsupported action '%s' for %s", act, e.path)
            continue
        # Normalize path to posix-like separators (keep as-is content)
        norm_path = e.path.replace("\\", "/").lstrip("./")
        cleaned.append(FileEdit(action=act, path=norm_path, content=e.content or ""))

    return cleaned


@tool(name="apply_changes", description="Apply file edits (create/modify/delete) to working tree.")
def apply_changes(repo_dir: str, edits: List[FileEdit]) -> dict:
    """
    Apply edits to disk safely. Returns summary with applied files.
    """
    applied: List[str] = []
    deleted: List[str] = []
    skipped: List[str] = []

    for e in edits:
        try:
            target = _safe_join(repo_dir, e.path)

            if e.action == "delete":
                if os.path.exists(target):
                    os.remove(target)
                    applied.append(e.path)
                    deleted.append(e.path)
                else:
                    skipped.append(e.path)
                continue

            # create / modify → ensure parent exists, write content
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(_ensure_trailing_newline(e.content))
            applied.append(e.path)

        except Exception as ex:  # keep going on individual failures
            log.error("Failed to apply %s %s: %s", e.action, e.path, ex)
            skipped.append(e.path)

    return {
        "applied_count": len(applied),
        "deleted_count": len(deleted),
        "applied_files": applied,
        "deleted_files": deleted,
        "skipped_files": skipped,
    }


@tool(name="build_and_test", description="Run build & test in an ephemeral Docker runner.")
def build_and_test(req: Requirement, repo_dir: str) -> dict:
    """
    Execute the requirement's build command inside an ephemeral container via DockerRunner.
    """
    b: BuildSpec = req.build
    runner = DockerRunner(
        image=b.container_image,
        workdir=b.workdir,
        env=b.env,
        cpu_shares=b.cpu_shares,
        mem_limit=b.mem_limit,
        timeout_seconds=b.timeout_seconds,
    )
    status, logs = runner.run(repo_dir, b.command)
    # keep logs reasonably bounded in memory; rely on artifacts_dir for full logs if needed
    preview = logs if isinstance(logs, str) and len(logs) <= 20000 else (logs[:20000] + "\n[...truncated...]")
    return {"status": status, "logs": preview}
