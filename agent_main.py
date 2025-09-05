
from __future__ import annotations
import os
from strands import Agent
from app.tools.requirements_tool import load_requirement
from app.tools.git_tools import prepare_workspace, commit_and_push
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test
from app.tools.github_tools import open_pull_request
from app.orchestrator import run_requirement_pipeline

def make_agent() -> Agent:
    """Construct a Strands agent wired with orchestration + point tools."""
    # Optional OpenTelemetry via StrandsTelemetry (best-effort)
    try:
        from strands.telemetry import StrandsTelemetry  # type: ignore
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            t = StrandsTelemetry()
            t.setup_otlp_exporter()
            if os.getenv("OTEL_CONSOLE_EXPORT", "0") in {"1","true","True"}:
                t.setup_console_exporter()
    except Exception:
        pass
    return Agent(
        name=os.getenv("AGENT_NAME", "Strands CodeOps Agent"),
        tools=[
            run_requirement_pipeline,
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
    a = make_agent()
    print("Agent ready. See README for usage.")
