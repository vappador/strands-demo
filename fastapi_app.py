
from __future__ import annotations
import asyncio
from typing import Optional, Any, Dict
from fastapi import FastAPI, Body
from pydantic import BaseModel
from agent_main import make_agent

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

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    # The tool is sync; run it in a worker thread so we don't block the event loop
    def _call():
        return _agent.tool.run_requirement_pipeline(requirement_source=req.requirement_source)
    result = await asyncio.to_thread(_call)
    return result  # Pydantic will coerce to RunResponse
