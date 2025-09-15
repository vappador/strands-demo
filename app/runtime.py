from __future__ import annotations

"""Lightweight runtime state for the agent.

Stores the active Agent instance and the most recent workspace information
returned by ``prepare_workspace`` so tools like ``search_context`` can infer the
repository directory without requiring the caller to pass it explicitly.
"""

from typing import Any, Optional, Dict

_AGENT: Optional[Any] = None
_WORKSPACE: Optional[Dict[str, Any]] = None


def set_agent(agent: Any) -> None:
    """Register the active Agent instance."""

    global _AGENT
    _AGENT = agent


def get_agent() -> Optional[Any]:
    """Return the current Agent instance, if any."""

    return _AGENT


def set_workspace(ws: Dict[str, Any] | None) -> None:
    """Store workspace metadata (e.g., repo_dir) for later tool use."""

    global _WORKSPACE
    _WORKSPACE = ws


def get_workspace() -> Optional[Dict[str, Any]]:
    """Return the most recently prepared workspace, if any."""

    return _WORKSPACE

