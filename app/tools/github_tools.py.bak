
from __future__ import annotations
import os, requests
from typing import Optional
from strands import tool
from app.models import Requirement

@tool(name="open_pull_request", description="Open a GitHub PR for the feature branch.")
def open_pull_request(req: Requirement, owner: str, repo_name: str, head_branch: str, last_commit_sha: str) -> Optional[str]:
    token = os.getenv("GITHUB_TOKEN")
    if not token: return None
    url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    payload = {
        "title": f"{req.id}: {req.title}",
        "head": head_branch,
        "base": (req.github.base if req.github else req.repo.default_branch),
        "body": req.codegen.description,
        "draft": (req.github.draft if req.github else False),
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    pr = r.json()
    pr_url = pr.get("html_url")

    # Optional reviewers
    if req.github and req.github.reviewers:
        try:
            rv = requests.post(
                f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr['number']}/requested_reviewers",
                headers=headers,
                json={"reviewers": [u for u in req.github.reviewers if "/" not in u],
                      "team_reviewers": [u.split("/")[1] for u in req.github.reviewers if "/" in u]},
                timeout=30,
            )
            rv.raise_for_status()
        except Exception:
            pass

    # Optional labels
    if req.github and req.github.labels:
        try:
            lb = requests.post(
                f"https://api.github.com/repos/{owner}/{repo_name}/issues/{pr['number']}/labels",
                headers=headers,
                json={"labels": req.github.labels},
                timeout=30,
            )
            lb.raise_for_status()
        except Exception:
            pass
    return pr_url
