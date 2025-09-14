from __future__ import annotations

import inspect
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple, List
from types import SimpleNamespace as _NS
from app import runtime

from strands import tool  # type: ignore

from app.models import Requirement
from app.tools.requirements_tool import load_requirement, RequirementLoadError
from app.tools.git_tools import prepare_workspace, commit_and_push
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test
from app.tools.github_tools import open_pull_request
from app.observability import observability

log = logging.getLogger(__name__)

def _underlying_callable(fn):
    try:
        return getattr(fn, "_tool_func", fn)
    except Exception:
        return fn

def _value_for(name: str, *, req: Requirement, ws: Optional[Dict[str, Any]], plan, changes, test_result):
    run_id = req.id
    repo_dir = (ws or {}).get("repo_dir") if isinstance(ws, dict) else None
    mapping = {
        "requirement": req, "req": req, "r": req,
        "run_id": run_id, "rid": run_id,
        "ws": ws, "workspace": ws,
        "repo_url": str(getattr(getattr(req, "repo", None), "url", "")),
        "repo_dir": repo_dir, "workdir": repo_dir, "cwd": repo_dir, "root": repo_dir, "path": repo_dir,
        "plan": plan, "plan_context": plan,
        "changes": changes, "diff": changes, "edits": changes, "patches": changes,
        "test_result": test_result, "tests_result": test_result,
        "base_branch": req.repo.default_branch, "default_branch": req.repo.default_branch,
        "branch_name": req.branch.branch_name(), "feature_branch": req.branch.branch_name(),
    }
    return mapping.get(name, inspect._empty)

def _smart_call(fn, *, req: Requirement, ws: Optional[Dict[str, Any]] = None,
                plan: Any = None, changes: Any = None, test_result: Any = None) -> Any:
    """
    Invoke a @tool function safely. We pass ONLY keyword arguments so we don't
    accidentally bind positional parameters like `tool_context` to strings (e.g., repo_dir).
    """
    target = _underlying_callable(fn)
    sig = inspect.signature(target)

    # Build kwargs only
    kwargs: Dict[str, Any] = {}
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        val = _value_for(p.name, req=req, ws=ws, plan=plan, changes=changes, test_result=test_result)
        if val is inspect._empty:
            continue
        kwargs[p.name] = val  # always keyword, never positional

    param_names = [p.name for p in sig.parameters.values() if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]

    # If the tool expects a tool_context, provide one with the current Agent
    if "tool_context" in param_names and "tool_context" not in kwargs:
        agent = runtime.get_agent()
        if agent is None:
            log.error("smart_call: tool '%s' expects tool_context, but no Agent is registered", getattr(target, "__name__", str(target)))
            raise TypeError("No Agent available to build tool_context")
        kwargs["tool_context"] = _NS(agent=agent)

    log.debug("smart_call: target=%s expected=%r provided=%r",
              getattr(target, "__name__", str(target)), param_names, list(kwargs.keys()))

    try:
        return fn(**kwargs)
    except TypeError as te:
        log.warning("smart_call: primary TypeError: %s; trying keyword-only fallbacks", te)

    # Fallback: keyword-only variants (no positional args to avoid misbinding)
    repo_dir = (ws or {}).get("repo_dir") if isinstance(ws, dict) else None
    kw_fallbacks: List[Dict[str, Any]] = [
        {"requirement": req, "repo_dir": repo_dir},
        {"req": req, "cwd": repo_dir},
        {"requirement": req, "repo_dir": repo_dir, "plan": plan, "changes": changes, "test_result": test_result},
    ]
    for i, kw in enumerate(kw_fallbacks, 1):
        try:
            log.debug("smart_call: fallback #%d %s(**%r)", i, getattr(target, "__name__", str(target)), kw)
            return fn(**kw)
        except TypeError as te:
            log.debug("smart_call: fallback #%d TypeError: %s", i, te)

    raise TypeError(f"Could not match arguments for tool '{getattr(target, '__name__', target)}'. Signature={sig}.")

@tool(name="run_requirement_pipeline", description="Run end-to-end pipeline from requirement YAML → PR.")
def run_requirement_pipeline(requirement_source: str) -> dict:
    """
    Orchestrates: load → prepare → plan → generate → apply → test → commit/push → PR
    Controlled by VERBOSE_RUN env var for whether to collect a timeline.
    """
    verbose = os.getenv("VERBOSE_RUN", "0") not in ("0", "", "false", "False")
    t0 = time.time()
    timeline: List[Dict[str, Any]] = []

    def _stage(name: str, fn, **kwargs):
        s0 = time.time()
        log.info("orchestrator: → %s", name)
        observability.stage_start(name)
        out = None
        try:
            out = _smart_call(fn, **kwargs)
            return out
        finally:
            dur = round(time.time() - s0, 3)
            log.info("orchestrator: ← %s (%.3fs)", name, dur)
            preview = None
            if verbose:
                # keep a light footprint to avoid huge responses
                try:
                    if isinstance(out, dict):
                        preview = {k: out[k] for k in list(out)[:5]}
                except Exception:
                    pass
                timeline.append({"stage": name, "duration_s": dur, "preview": preview})
            observability.stage_end(name, preview)
            observability.add_message("stage", f"{name} completed in {dur}s")

    # 1) load
    observability.start_run()
    try:
        req: Requirement = load_requirement(requirement_source)
    except RequirementLoadError as e:
        log.error("orchestrator: load_requirement failed where=%s message=%s", e.where, e.message)
        observability.add_message("error", f"load_requirement failed: {e.message}")
        observability.finish_run("error")
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
            "timeline": timeline if verbose else None,
        }

    log.info("orchestrator: start id=%s title=%s", req.id, req.title)
    observability.add_message("system", f"start {req.id}: {req.title}")

    try:
        ws = _stage("prepare_workspace", prepare_workspace, req=req, ws=None)
        repo = str(req.repo.url)
        branch = req.branch.branch_name()

        plan = _stage("plan_changes", plan_changes, req=req, ws=ws)
        changes = _stage("generate_changes", generate_changes, req=req, ws=ws, plan=plan)
        applied = _stage("apply_changes", apply_changes, req=req, ws=ws, changes=changes)
        test_result = _stage("build_and_test", build_and_test, req=req, ws=ws)

        commit_info = commit_and_push(ws["repo_dir"], req.title)
        if verbose:
            timeline.append({"stage": "commit_and_push", "duration_s": None, "preview": {"last_commit": commit_info.get("last_commit")}})

        pr_url = None
        if req.github and req.github.create_pr and os.getenv("GITHUB_TOKEN"):
            pr_url = open_pull_request(
                req,
                ws.get("owner", ""),
                ws.get("repo_name", ""),
                branch,
                commit_info.get("last_commit"),
            )
            if verbose:
                timeline.append({"stage": "open_pull_request", "duration_s": None, "preview": {"pr_url": pr_url}})

        total = round(time.time() - t0, 3)
        exit_code = (test_result or {}).get("status")
        logs = (test_result or {}).get("logs", "")
        # strict success only if tests passed (0 or "0")
        success = str(exit_code) in ("0", "None") or exit_code == 0
        status = "success" if success else "error"

        observability.finish_run(status)
        observability.add_message("system", f"run finished: {status}")
        return {
            "status": status,
            "branch": branch,
            "repo": repo,
            "pr_url": pr_url,
            "test_exit_code": exit_code,
            "test_logs": logs,
            "applied": applied,
            "elapsed_seconds": total,
            "where": None,
            "message": None,
            "validation_errors": None,
            "timeline": timeline if verbose else None,
        }

    except Exception as e:
        log.exception("orchestrator: unhandled failure")
        observability.add_message("error", str(e))
        observability.finish_run("error")
        return {
            "status": "error",
            "where": "orchestrator",
            "message": str(e),
            "branch": branch if 'branch' in locals() else None,
            "repo": repo if 'repo' in locals() else None,
            "pr_url": None,
            "test_exit_code": None,
            "test_logs": None,
            "applied": None,
            "elapsed_seconds": round(time.time() - t0, 3),
            "timeline": timeline if verbose else None,
        }
