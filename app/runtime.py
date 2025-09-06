from __future__ import annotations
from typing import Any, Optional

_AGENT: Optional[Any] = None

def set_agent(agent: Any) -> None:
    global _AGENT
    _AGENT = agent

def get_agent() -> Optional[Any]:
    return _AGENT