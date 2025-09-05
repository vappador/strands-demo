
from __future__ import annotations
import os
from strands import tool
from app.models import Requirement
from app.tools.requirements_tool import load_requirement
from app.tools.git_tools import prepare_workspace, commit_and_push
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test
from app.tools.github_tools import open_pull_request

@tool(name="run_requirement_pipeline", description="Run end-to-end pipeline from requirement YAML → PR.")
def run_requirement_pipeline(requirement_source: str) -> dict:
    req: Requirement = load_requirement(requirement_source)
    ws = prepare_workspace(req.id, str(req.repo.url), req.branch.branch_name(), req.repo.default_branch)
    plan = plan_changes(req, ws["repo_dir"])
    changes = generate_changes(req, plan, ws["repo_dir"])
    apply_info = apply_changes(ws["repo_dir"], changes)
    test_result = build_and_test(req, ws["repo_dir"])
    commit_info = commit_and_push(ws["repo_dir"], req.title)
    pr_url = None
    if req.github and req.github.create_pr and os.getenv("GITHUB_TOKEN"):
        pr_url = open_pull_request(req, ws["owner"], ws["repo_name"], req.branch.branch_name(), commit_info["last_commit"])
    return {
        "status": "success" if test_result.get("status") == 0 else "error",
        "branch": req.branch.branch_name(),
        "repo": str(req.repo.url),
        "pr_url": pr_url,
        "test_exit_code": test_result.get("status"),
        "test_logs": test_result.get("logs",""),
        "applied": apply_info,
    }
