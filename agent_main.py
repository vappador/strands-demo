from __future__ import annotations

import logging
import os
import uuid

from strands import Agent
from app.tools.requirements_tool import load_requirement  # tool (kept)
from app.tools.git_tools import prepare_workspace, commit_and_push
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test
from app.tools.github_tools import open_pull_request
from app.orchestrator import run_requirement_pipeline

log = logging.getLogger(__name__)

def make_agent() -> Agent:
    """Construct a Strands agent with orchestration + point tools, preserving decorators."""
    # Optional OpenTelemetry via StrandsTelemetry (best-effort)
    try:
        from strands.telemetry import StrandsTelemetry  # type: ignore
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            StrandsTelemetry(service_name="strands-codeops-agent").install()
            log.info("agent_main: OpenTelemetry configured")
    except Exception:
        log.debug("agent_main: OTEL not configured", exc_info=True)

    return Agent(
        name="codeops-agent",
        description="Agent that reads requirements and turns them into PRs.",
        tools=[
            run_requirement_pipeline,  # orchestration tool
            load_requirement,
            prepare_workspace,
            plan_changes,
            generate_changes,
            apply_changes,
            build_and_test,
            commit_and_push,
            open_pull_request,
        ],
    )

if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    a = make_agent()
    log.info("Agent ready. See README for usage.")
