# app/fastapi_app.py
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Any, Dict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.observability import observability, _init_otel_tracing_once
from agent_main import make_agent

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ------------------------------------------------------------------ OTEL init
# Make sure OTEL tracing is initialized before FastAPI app is created
try:
    _init_otel_tracing_once()
except Exception as e:
    logging.getLogger(__name__).warning("OTEL init failed: %s", e)

# ------------------------------------------------------------------ FastAPI app
app = FastAPI(title="Strands CodeOps Agent API", version="1.0.0")
_agent = make_agent()


# ------------------------------------------------------------------ models
class RunRequest(BaseModel):
    """Request body for the /run endpoint."""

    requirement_source: str
    verbose: Optional[bool] = False


class RunResponse(BaseModel):
    """Response returned by the /run endpoint."""

    status: str
    branch: Optional[str] = None
    repo: Optional[str] = None
    pr_url: Optional[str] = None
    test_exit_code: Optional[int] = None
    test_logs: Optional[str] = None
    applied: Optional[Dict[str, Any]] = None
    where: Optional[str] = None
    message: Optional[str] = None
    validation_errors: Optional[list] = None
    elapsed_seconds: Optional[float] = None
    timeline: Optional[list] = None  # include timeline from observability


# ------------------------------------------------------------------ endpoints
@app.get("/health")
async def health() -> Dict[str, bool]:
    """Simple health check endpoint."""
    return {"ok": True}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    """Execute the requirement pipeline in a worker thread."""

    def _call():
        # This will use observability spans/events underneath
        return _agent.tool.run_requirement_pipeline(
            requirement_source=req.requirement_source,
            stream=True,
        )

    return await asyncio.to_thread(_call)


@app.get("/status")
async def status() -> Dict[str, Any]:
    """Return current observability snapshot (for UI polling)."""
    return observability.snapshot()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Simple web UI to display current status and conversation."""
    html = """
    <html>
    <head><title>Strands Status</title></head>
    <body>
    <h1>Strands Status</h1>
    <div id='state'></div>
    <h2>Conversation</h2>
    <ul id='conv'></ul>
    <script>
    async function refresh() {
        const res = await fetch('/status');
        const data = await res.json();
        document.getElementById('state').innerText = 'Status: ' + data.status + ' | Stage: ' + data.current_stage;
        const ul = document.getElementById('conv');
        ul.innerHTML = '';
        data.conversation.forEach(m => {
            const li = document.createElement('li');
            li.textContent = m.role + ': ' + m.content;
            ul.appendChild(li);
        });
    }
    refresh();
    setInterval(refresh, 1000);
    </script>
    </body></html>
    """
    return HTMLResponse(html)
