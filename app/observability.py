import time
from threading import Lock
from typing import Any, Dict, List


class Observability:
    """Simple in-memory state store for tracking runs and reasoning output."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        """Reset internal state to idle."""
        with self._lock:
            self.status: str = "idle"
            self.current_stage: str | None = None
            self.timeline: List[Dict[str, Any]] = []
            self.conversation: List[Dict[str, Any]] = []
            self.started_at: float | None = None

    # --- run level helpers -------------------------------------------------
    def start_run(self) -> None:
        with self._lock:
            self.reset()
            self.started_at = time.time()
            self.status = "running"

    def finish_run(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.current_stage = None

    # --- stage helpers -----------------------------------------------------
    def stage_start(self, name: str) -> None:
        with self._lock:
            self.current_stage = name
            self.timeline.append({"stage": name, "start": time.time()})

    def stage_end(self, name: str, preview: Any | None = None) -> None:
        with self._lock:
            end = time.time()
            if self.timeline and self.timeline[-1]["stage"] == name:
                info = self.timeline[-1]
                info["end"] = end
                info["duration"] = round(end - info["start"], 3)
                if preview is not None:
                    info["preview"] = preview
            self.current_stage = None

    # --- conversation helpers ---------------------------------------------
    def add_message(self, role: str, content: str) -> None:
        with self._lock:
            self.conversation.append({
                "role": role,
                "content": content,
                "time": time.time(),
            })

    # --- retrieval ---------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "current_stage": self.current_stage,
                "timeline": list(self.timeline),
                "conversation": list(self.conversation),
                "started_at": self.started_at,
            }


observability = Observability()
