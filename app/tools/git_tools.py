
from __future__ import annotations
import os, re
from urllib.parse import urlparse
from git import Repo
from strands import tool
from app.utils import ensure_dir

@tool(name="prepare_workspace", description="Clone repo and create a feature branch for the job.")
def prepare_workspace(job_id: str, repo_url: str, branch_name: str, base_branch: str="main") -> dict:
    base_dir = os.getenv("WORKSPACE_DIR", "/workspace/jobs")
    job_dir = os.path.join(base_dir, job_id)
    repo_dir = os.path.join(job_dir, "repo")
    ensure_dir(job_dir)

    parsed = urlparse(repo_url)
    token = os.getenv("GITHUB_TOKEN")
    auth_url = repo_url
    if token and parsed.scheme.startswith("http") and parsed.netloc == "github.com":
        auth_url = f"https://{token}:x-oauth-basic@github.com{parsed.path}"

    if not os.path.exists(repo_dir):
        Repo.clone_from(auth_url, repo_dir)

    repo = Repo(repo_dir)
    repo.git.fetch("origin", base_branch)
    repo.git.checkout(base_branch)
    repo.git.pull("origin", base_branch)

    try:
        repo.git.checkout("-b", branch_name)
    except Exception:
        repo.git.checkout(branch_name)

    repo.git.push("-u", "origin", branch_name)
    owner, repo_name = _owner_repo_from_url(repo_url)
    return {"repo_dir": repo_dir, "owner": owner, "repo_name": repo_name}

def _owner_repo_from_url(repo_url: str) -> tuple[str,str]:
    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", repo_url)
    if not m: return ("","")
    return m.group(1), m.group(2)

@tool(name="commit_and_push", description="Commit all changes and push to origin.")
def commit_and_push(repo_dir: str, message: str) -> dict:
    repo = Repo(repo_dir)
    repo.git.add(all=True)
    if repo.is_dirty():
        repo.index.commit(message)
        repo.git.push("origin", repo.active_branch.name)
    head = repo.head.commit.hexsha
    return {"last_commit": head}
