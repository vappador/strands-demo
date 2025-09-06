from __future__ import annotations

import os
import logging
import yaml
from pydantic import ValidationError

from strands import tool
from app.models import Requirement, format_validation_errors

log = logging.getLogger(__name__)

class RequirementLoadError(Exception):
    def __init__(self, where: str, message: str, validation_errors: list | None = None):
        super().__init__(message)
        self.where = where
        self.message = message
        self.validation_errors = validation_errors or []

@tool(name="load_requirement", description="Load and validate a requirement YAML from path or raw text.")
def load_requirement(requirement_source: str) -> Requirement:
    """
    Accepts either a filesystem path (inside the container) OR a raw YAML string.
    Logs how the input is resolved and raises RequirementLoadError with rich details on failure.
    """
    try:
        if os.path.exists(requirement_source):
            log.info("requirements_tool: loading requirement from FILE: %s", requirement_source)
            with open(requirement_source, "r", encoding="utf-8") as f:
                raw = f.read()
            log.debug("requirements_tool: file bytes=%d", len(raw.encode("utf-8")))
        else:
            log.info("requirements_tool: treating input as RAW YAML (path not found): %s", requirement_source)
            raw = requirement_source
            if ("\n" not in raw) and (":" not in raw):
                log.warning("requirements_tool: RAW YAML looks like a bare string (likely a missing bind mount)")

        data = yaml.safe_load(raw)
        log.debug("requirements_tool: yaml.safe_load type=%s", type(data).__name__)

        if not isinstance(data, dict):
            raise RequirementLoadError(
                where="requirements_tool.safe_load",
                message=f"Top-level YAML is {type(data).__name__}, expected mapping/dict",
            )

        log.info("requirements_tool: parsed top-level keys: %s", sorted(list(data.keys())))

        try:
            req = Requirement(**data)
            log.info("requirements_tool: Requirement parsed OK: id=%s title=%s", req.id, req.title)
            return req
        except ValidationError as ve:
            errs = format_validation_errors(ve)
            for e in errs:
                log.error("requirements_tool: validation error loc=%s msg=%s type=%s",
                          e.get("loc"), e.get("msg"), e.get("type"))
            raise RequirementLoadError(
                where="models.Requirement",
                message="Requirement validation failed",
                validation_errors=errs,
            )

    except RequirementLoadError:
        # rethrow so orchestrator can include details in the HTTP response
        raise
    except Exception as e:
        log.exception("requirements_tool: unexpected error while loading requirement")
        raise RequirementLoadError(where="requirements_tool.load_requirement", message=str(e))