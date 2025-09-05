
from __future__ import annotations
import os, yaml
from strands import tool
from app.models import Requirement

@tool(name="load_requirement", description="Load and validate a requirement YAML from path or raw text.")
def load_requirement(requirement_source: str) -> Requirement:
    if os.path.exists(requirement_source):
        raw = open(requirement_source, "r", encoding="utf-8").read()
    else:
        raw = requirement_source
    data = yaml.safe_load(raw)
    return Requirement(**data)
