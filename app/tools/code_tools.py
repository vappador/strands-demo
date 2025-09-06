from __future__ import annotations
import os
from typing import List
from pydantic import BaseModel
from strands import tool, ToolContext
from app.models import Requirement, BuildSpec
from app.runners import DockerRunner


class FileEdit(BaseModel):
    action: str  # "create" | "modify"
    path: str
    content: str


class ChangePlan(BaseModel):
    summary: str
    touched_files: List[str] = []


@tool(context=True, name="plan_changes", description="Summarize repo & plan edits for the requirement.")
def plan_changes(tool_context: ToolContext, req: Requirement, repo_dir: str) -> ChangePlan:
    inventory = _scan_repo(repo_dir)
    prompt = f"""
You are a senior engineer. Given this requirement, output a concise plan.

REQUIREMENT TITLE: {req.title}
REQ ID: {req.id}
LANGUAGE: {req.language}
CODE INSTRUCTION:\n{req.codegen.description}\n
REPO INVENTORY (paths):\n{inventory}\n
Return a JSON with fields: summary (string), touched_files (array of strings).
"""
    return tool_context.agent.structured_output(ChangePlan, prompt)


def _scan_repo(repo_dir: str, max_files: int = 200) -> str:
    out = []
    for root, dirs, files in os.walk(repo_dir):
        if any(seg.startswith(".") for seg in root.split(os.sep)): continue
        for f in files:
            if f.endswith((".py", ".ts", ".js", ".java", ".md", ".yml", ".yaml")):
                rel = os.path.relpath(os.path.join(root, f), repo_dir)
                out.append(rel)
            if len(out) >= max_files:
                return "\n".join(out)
    return "\n".join(out)


@tool(context=True, name="generate_changes", description="Generate concrete file edits for the requirement.")
def generate_changes(tool_context: ToolContext, req: Requirement, plan: ChangePlan, repo_dir: str) -> List[FileEdit]:
    schema_hint = "Return a JSON array of {action['create'|'modify'], path, content}."
    test_hints = "\n".join(f"- {x}" for x in req.codegen.test_expectations)
    prompt = f"""
You will propose precise file edits to implement the requirement.
- Only return JSON. {schema_hint}
- Prefer minimal changes.
- Include unit tests matching these expectations:\n{test_hints}

REQ ID: {req.id}\nTITLE: {req.title}\nLANGUAGE: {req.language}
PLAN SUMMARY: {plan.summary}\nTOUCH LIST: {plan.touched_files}
REPO ROOT: {repo_dir}
"""
    return tool_context.agent.structured_output(List[FileEdit], prompt)


@tool(name="apply_changes", description="Apply file edits (create/modify) to working tree.")
def apply_changes(repo_dir: str, edits: List[FileEdit]) -> dict:
    applied = []
    for e in edits:
        target = os.path.join(repo_dir, e.path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if e.action not in {"create", "modify"}: continue
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(e.content)
        applied.append(e.path)
    return {"applied_count": len(applied), "files": applied}


@tool(name="build_and_test", description="Run build & test in an ephemeral Docker runner.")
def build_and_test(req: Requirement, repo_dir: str) -> dict:
    b: BuildSpec = req.build
    runner = DockerRunner(image=b.container_image, workdir=b.workdir, env=b.env,
                          cpu_shares=b.cpu_shares, mem_limit=b.mem_limit, timeout_seconds=b.timeout_seconds)
    status, logs = runner.run(repo_dir, b.command)
    return {"status": status, "logs": logs}
