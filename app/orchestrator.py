from __future__ import annotations

import logging
import os
import time

from strands import tool
from app.models import Requirement
from app.tools.requirements_tool import load_requirement, RequirementLoadError
from app.tools.git_tools import prepare_workspace, commit_and_push
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test
from app.tools.github_tools import open_pull_request

log = logging.getLogger(__name__)

@tool(name="run_requirement_pipeline", description="Run end-to-end pipeline from requirement YAML → PR.")
def run_requirement_pipeline(requirement_source: str) -> dict:
    """
    Orchestrates: load → prepare → plan → generate → apply → test → commit/push → PR
    Returns a structured dict with status plus rich error details when something fails.
    """
    t0 = time.time()
    try:
        req: Requirement = load_requirement(requirement_source)
    except RequirementLoadError as e:
        log.error("orchestrator: load_requirement failed where=%s message=%s", e.where, e.message)
        return {
            "status": "error",
            "where": e.where,
            "message": e.message,
            "validation_errors": getattr(e, "validation_errors", []),
            "branch": None,
            "repo": None,
            "pr_url": None,
            "test_exit_code": None,
            "test_logs": None,
            "applied": None,
            "elapsed_seconds": round(time.time() - t0, 3),
        }

    log.info("orchestrator: start id=%s title=%s", req.id, req.title)

    def stage(name: str, fn, *a, **kw):
        s0 = time.time()
        log.info("orchestrator: → %s", name)
        out = fn(*a, **kw)
        log.info("orchestrator: ← %s (%.3fs)", name, time.time() - s0)
        return out

    try:
        # prepare workspace (clone repo, checkout base, create feature branch)
        ws = stage("prepare_workspace", prepare_workspace, req.id, str(req.repo.url), req.branch.branch_name(), req.repo.default_branch)

        # plan with LLM (kept as your tool; no schema changes)
        plan = stage("plan_changes", plan_changes, req, ws["repo_dir"])

        # generate file edits
        changes = stage("generate_changes", generate_changes, req, plan, ws["repo_dir"])

        # apply edits to the working tree
        apply_info = stage("apply_changes", apply_changes, changes, ws["repo_dir"])

        # build & test using Docker runner
        test_result = stage("build_and_test", build_and_test, req, ws["repo_dir"])

        # commit & push
        commit_info = stage("commit_and_push", commit_and_push, ws["repo_dir"], req.title)

        # optionally open PR (needs token)
        pr_url = None
        if req.github and req.github.create_pr and os.getenv("GITHUB_TOKEN"):
            pr_url = stage(
                "open_pull_request",
                open_pull_request,
                req,
                ws["owner"],
                ws["repo_name"],
                req.branch.branch_name(),
                commit_info.get("last_commit"),
            )

        total = round(time.time() - t0, 3)
        status = "success" if (test_result or {}).get("status") in (0, "0") else "error"
        log.info("orchestrator: done in %.3fs status=%s pr=%s", total, status, pr_url)

        return {
            "status": status,
            "branch": req.branch.branch_name(),
            "repo": str(req.repo.url),
            "pr_url": pr_url,
            "test_exit_code": (test_result or {}).get("status"),
            "test_logs": (test_result or {}).get("logs", ""),
            "applied": apply_info,
            "elapsed_seconds": total,
        }

    except Exception as e:
        log.exception("orchestrator: unhandled failure")
        return {
            "status": "error",
            "where": "orchestrator",
            "message": str(e),
            "branch": None,
            "repo": str(req.repo.url) if getattr(req, "repo", None) else None,
            "pr_url": None,
            "test_exit_code": None,
            "test_logs": None,
            "applied": None,
            "elapsed_seconds": round(time.time() - t0, 3),
        }
