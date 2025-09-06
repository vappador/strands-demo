from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Any, Dict

from fastapi import FastAPI, Body
from pydantic import BaseModel

from agent_main import make_agent

# Basic logging setup (keeps your production defaults but ensures we see our new logs)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(title="Strands CodeOps Agent API", version="1.0.0")
_agent = make_agent()

class RunRequest(BaseModel):
    requirement_source: str  # path to YAML or raw YAML content

class RunResponse(BaseModel):
    status: str
    branch: Optional[str] = None
    repo: Optional[str] = None
    pr_url: Optional[str] = None
    test_exit_code: Optional[int] = None
    test_logs: Optional[str] = None
    applied: Optional[Dict[str, Any]] = None
    # New optional error fields (the tool returns them when something fails)
    where: Optional[str] = None
    message: Optional[str] = None
    validation_errors: Optional[list] = None
    elapsed_seconds: Optional[float] = None

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    # Keep tool execution off the event loop
    def _call():
        return _agent.tool.run_requirement_pipeline(requirement_source=req.requirement_source)
    result = await asyncio.to_thread(_call)
    return result