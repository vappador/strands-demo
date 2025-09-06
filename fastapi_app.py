# fastapi_app.py
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

from agent_main import make_agent

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(title="Strands CodeOps Agent API", version="1.0.0")
_agent = make_agent()

class RunRequest(BaseModel):
    requirement_source: str
    verbose: Optional[bool] = False

class RunResponse(BaseModel):
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
    timeline: Optional[list] = None  # <-- new

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    def _call():
        # pass verbose through to the tool
        return _agent.tool.run_requirement_pipeline(requirement_source=req.requirement_source, verbose=req.verbose or False)
    return await asyncio.to_thread(_call)
