from __future__ import annotations
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field, HttpUrl, ValidationError

# --- Your existing models (unchanged shape) ---

class RepoSpec(BaseModel):
    url: HttpUrl
    default_branch: str = Field(default="main")

class BranchSpec(BaseModel):
    feature_id: str
    name_template: str = Field(default="feature/{feature_id}")
    def branch_name(self) -> str:
        return self.name_template.format(feature_id=self.feature_id)

class BuildSpec(BaseModel):
    command: str
    container_image: str
    workdir: str = Field(default="/workspace")
    env: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=1800)
    cpu_shares: Optional[int] = None
    mem_limit: Optional[str] = None  # e.g., "4g"

class GitHubSpec(BaseModel):
    create_pr: bool = True
    base: str = Field(default="main")
    reviewers: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    draft: bool = False

class CodeInstruction(BaseModel):
    description: str = Field(description="Natural-language instructions for required change")
    test_expectations: List[str] = Field(default_factory=list)

class Requirement(BaseModel):
    id: str
    title: str
    language: Optional[Literal["python","node","java"]] = None
    repo: RepoSpec
    branch: BranchSpec
    build: BuildSpec
    github: Optional[GitHubSpec] = None
    codegen: CodeInstruction
    artifacts_dir: str = Field(default="/workspace/jobs/{id}")

class ChangePlan(BaseModel):
    summary: str
    touched_files: List[str] = Field(default_factory=list)

class FileEdit(BaseModel):
    action: Literal["create", "modify", "delete"]
    path: str
    content: str


# --- Helper for compact, JSON-safe Pydantic error formatting ---

def format_validation_errors(exc: ValidationError) -> List[Dict[str, Any]]:
    """
    Return a compact list like: [{"loc": [...], "msg": "...", "type": "..."}].
    """
    out: List[Dict[str, Any]] = []
    for err in exc.errors():
        out.append({
            "loc": err.get("loc"),
            "msg": err.get("msg"),
            "type": err.get("type"),
        })
    return out