# app/agent_main.py
from __future__ import annotations

import logging
import os
import inspect

# Force a non-Bedrock provider and block AWS IMDS lookups *before* importing Agent.
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("STRANDS_MODEL_PROVIDER", os.getenv("STRANDS_MODEL_PROVIDER", "ollama"))
os.environ.setdefault("OLLAMA_HOST", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
os.environ.setdefault("STRANDS_MODEL", os.getenv("STRANDS_MODEL", "qwen2.5-coder:3b"))

from strands import Agent
from strands.models.ollama import OllamaModel

# tools (kept)
from app.tools.requirements_tool import load_requirement  # noqa: F401
from app.tools.git_tools import prepare_workspace, commit_and_push  # noqa: F401
from app.tools.code_tools import plan_changes, generate_changes, apply_changes, build_and_test  # noqa: F401
from app.tools.github_tools import open_pull_request  # noqa: F401
from app.tools.search_context import search_context

# registers the @tool on import
from app.orchestrator import run_requirement_pipeline  # noqa: F401

from app import runtime
from app.observability import _init_otel_tracing_once

log = logging.getLogger(__name__)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    log.addHandler(_h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def _maybe_install_strands_telemetry() -> None:
    """
    Try to install StrandsTelemetry if present, regardless of version signature.
    Fall back silently if unavailable or if install fails. Your OTEL init in
    app/observability.py already sets up tracing.
    """
    try:
        # Older/newer packages place it under strands.observability (most common).
        from strands.observability import StrandsTelemetry  # type: ignore
    except Exception:
        log.debug("StrandsTelemetry not available; skipping.")
        return

    try:
        sig = inspect.signature(StrandsTelemetry)
        # If the current version accepts service_name, pass it; otherwise call no-arg.
        if "service_name" in sig.parameters:
            st = StrandsTelemetry(service_name=os.getenv("OTEL_SERVICE_NAME", "strands-codeops-agent"))  # type: ignore[arg-type]
        else:
            st = StrandsTelemetry()  # type: ignore[call-arg]
        st.install()  # type: ignore[attr-defined]
        log.info("StrandsTelemetry installed.")
    except TypeError as e:
        log.warning("StrandsTelemetry signature mismatch (%s); continuing with OTEL only.", e)
    except Exception as e:
        log.warning("StrandsTelemetry install failed (%s); continuing with OTEL only.", e)


def make_agent() -> Agent:
    """Construct a Strands agent with Ollama backend and optional telemetry."""
    # Ensure OTEL tracing is initialized (no-op if already set by fastapi_app)
    try:
        _init_otel_tracing_once()
    except Exception as e:
        log.warning("OTEL init failed: %s", e)

    # Best-effort Strands telemetry (optional)
    _maybe_install_strands_telemetry()

    # Build the model the usual way (env-driven)
    model_name = os.getenv("STRANDS_MODEL", "qwen2.5-coder:3b")
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    log.info("Connecting to Ollama at %s with model %s", ollama_host, model_name)
    model = OllamaModel(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        model_id=os.getenv("STRANDS_MODEL", "qwen2.5-coder:3b")
    )

    # Register agent in runtime for tools that need ToolContext/agent handle
    agent = Agent(
        name="codeops-agent",
        model=model,
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
            search_context,
        ],
    )
    runtime.set_agent(agent)
    return agent
