# app/observability.py
from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import Any, Dict, List, Optional

# --- OpenTelemetry imports (gracefully optional) ---------------------------
from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# OTLP (HTTP) exporter is optional; we degrade to console-only if missing
try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except Exception:  # pragma: no cover
    OTLPSpanExporter = None  # type: ignore

log = logging.getLogger(__name__)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    log.addHandler(_h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def _init_otel_tracing_once() -> None:
    """
    Initialize OTEL tracing once, with:
      - service.name from OTEL_SERVICE_NAME or default
      - OTLP HTTP exporter if OTEL_EXPORTER_OTLP_ENDPOINT is set
      - Console exporter if OTEL_CONSOLE_EXPORT=1 or OTEL_TRACES_EXPORTER=console
    If a real SDK provider is already installed (e.g., via opentelemetry-instrument),
    we leave it as-is and just return.
    """
    provider = trace.get_tracer_provider()
    # If SDK already configured, do nothing (prevents conflicts with auto-instrumentation)
    if isinstance(provider, TracerProvider):
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "strands-codeops-agent")
    resource = Resource.create({SERVICE_NAME: service_name})

    tracer_provider = TracerProvider(resource=resource)

    # OTLP HTTP exporter (to a collector, e.g., http://otel-collector:4318)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint and OTLPSpanExporter is not None:
        try:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)  # typical for local dev
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info("OTEL: Traces → OTLP HTTP at %s", otlp_endpoint)
        except Exception as e:  # pragma: no cover
            log.warning("OTEL: Failed to init OTLP exporter (%s). Falling back to console if enabled.", e)

    # Console exporter (debug-friendly)
    if os.getenv("OTEL_CONSOLE_EXPORT") == "1" or os.getenv("OTEL_TRACES_EXPORTER") == "console":
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        log.info("OTEL: Console trace exporter enabled")

    trace.set_tracer_provider(tracer_provider)


# Initialize tracing on import (safe: no-op if already set by auto-instrumentation)
try:
    _init_otel_tracing_once()
except Exception as e:  # pragma: no cover
    log.warning("OTEL init skipped due to error: %s", e)


class Observability:
    """
    Simple in-memory state store for tracking runs and reasoning output,
    augmented with OpenTelemetry tracing.

    Public API matches your original:
      - start_run()
      - finish_run(status)
      - stage_start(name)
      - stage_end(name, preview=None)
      - add_message(role, content)
      - snapshot()
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._tracer = trace.get_tracer("observability")
        # Spans we manage explicitly
        self._run_span: Optional[Span] = None
        self._stage_span: Optional[Span] = None
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        """Reset internal state to idle."""
        with self._lock:
            self.status: str = "idle"
            self.current_stage: Optional[str] = None
            self.timeline: List[Dict[str, Any]] = []
            self.conversation: List[Dict[str, Any]] = []
            self.started_at: Optional[float] = None

    # ------------------------------------------------------------ run helpers
    def start_run(self) -> None:
        with self._lock:
            # Close any dangling spans from a previous run (defensive)
            try:
                if self._stage_span is not None:
                    self._stage_span.end()
            except Exception:
                pass
            try:
                if self._run_span is not None:
                    self._run_span.end()
            except Exception:
                pass

            self.reset()
            self.started_at = time.time()
            self.status = "running"

            # Root run span
            self._run_span = self._tracer.start_span("run_requirement_pipeline")
            # Add basic attributes useful for search in Tempo/Grafana
            self._run_span.set_attribute("app.status", "running")
            self._run_span.set_attribute("service.name", os.getenv("OTEL_SERVICE_NAME", "strands-codeops-agent"))

            log.debug("Observability: run started")

    def finish_run(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.current_stage = None

            # End any open stage span first
            if self._stage_span is not None:
                try:
                    self._stage_span.set_attribute("stage.status", "ended_on_finish")
                finally:
                    self._stage_span.end()
                self._stage_span = None

            # Mark and end run span
            if self._run_span is not None:
                try:
                    self._run_span.set_attribute("app.status", status)
                    # Add a short event for timeline clarity
                    self._run_span.add_event(
                        "run.finished",
                        {
                            "status": status,
                            "duration_ms": int((time.time() - (self.started_at or time.time())) * 1000),
                        },
                    )
                finally:
                    self._run_span.end()
                self._run_span = None

            log.debug("Observability: run finished with status=%s", status)

    # ---------------------------------------------------------- stage helpers
    def stage_start(self, name: str) -> None:
        with self._lock:
            # Close previous stage if still open (defensive)
            if self._stage_span is not None:
                try:
                    self._stage_span.end()
                except Exception:
                    pass

            self.current_stage = name
            start_ts = time.time()
            self.timeline.append({"stage": name, "start": start_ts})

            # Child span under the run span (if present)
            parent = self._run_span if self._run_span is not None else None
            self._stage_span = self._tracer.start_span(f"stage:{name}", context=trace.set_span_in_context(parent) if parent else None)
            self._stage_span.set_attribute("stage.name", name)
            self._stage_span.add_event("stage.start", {"name": name, "time_unix": int(start_ts * 1e9)})

            # Also log for visibility in docker logs
            log.info("Stage started: %s", name)

    def stage_end(self, name: str, preview: Any | None = None) -> None:
        with self._lock:
            end_ts = time.time()
            if self.timeline and self.timeline[-1]["stage"] == name:
                info = self.timeline[-1]
                info["end"] = end_ts
                info["duration"] = round(end_ts - info["start"], 3)
                if preview is not None:
                    info["preview"] = preview

            # Gracefully handle mismatched names
            if self._stage_span is not None:
                try:
                    if preview is not None:
                        # Keep preview small in attributes to avoid giant spans
                        preview_text = str(preview)
                        if len(preview_text) > 1024:
                            preview_text = preview_text[:1024] + "…"
                        self._stage_span.add_event("stage.preview", {"preview": preview_text})

                    self._stage_span.add_event("stage.end", {"name": name, "time_unix": int(end_ts * 1e9)})
                finally:
                    self._stage_span.end()
                self._stage_span = None

            self.current_stage = None
            log.info("Stage ended: %s", name)

    # ------------------------------------------------------ conversation log
    def add_message(self, role: str, content: str) -> None:
        with self._lock:
            ts = time.time()
            self.conversation.append({"role": role, "content": content, "time": ts})

            # Attach message as an OTEL event to the current stage (preferred) or run span
            span = self._stage_span or self._run_span
            if span is not None:
                safe_content = content if len(content) <= 2048 else content[:2048] + "…"
                span.add_event(
                    "message",
                    {
                        "role": role,
                        "content": safe_content,
                        "time_unix": int(ts * 1e9),
                    },
                )

            log.debug("Conversation message added (role=%s, %d chars)", role, len(content))

    # --------------------------------------------------------------- snapshot
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "current_stage": self.current_stage,
                "timeline": list(self.timeline),
                "conversation": list(self.conversation),
                "started_at": self.started_at,
            }


# Singleton (same as your original)
observability = Observability()
