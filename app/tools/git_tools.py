from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict

from strands import tool  # type: ignore
from git import Repo, GitCommandError  # GitPython

log = logging.getLogger(__name__)

def _authed_https_url(repo_url: str, token: str | None) -> str:
    """
    If token provided, convert:
      https://github.com/owner/repo.git
    to
      https://x-access-token:{TOKEN}@github.com/owner/repo.git
    (recommended for GitHub tokens)
    """
    if not token:
        return repo_url
    if not repo_url.startswith("https://"):
        # leave ssh URLs alone
        return repo_url
    return re.sub(r"^https://", f"https://x-access-token:{token}@", repo_url)

def _run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err

@tool(name="prepare_workspace", description="Clone repo, checkout base, create feature branch, configure git identity & authed remote.")
def prepare_workspace(run_id: str, repo_url: str, branch_name: str, base_branch: str = "main") -> Dict:
    """
    - Clones the repository into /workspace/jobs/{run_id}/repo
    - Configures git user.{name,email} from env (with fallbacks)
    - If GITHUB_TOKEN present, rewrites origin URL to an authed https URL
    - Checks out base_branch and creates branch_name
    - Pushes branch to origin (auth required)
    Returns basic info: owner, repo_name, repo_dir.
    """
    jobs_dir = Path("/workspace/jobs") / run_id
    repo_dir = jobs_dir / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)

    log.info("git_tools: cloning %s → %s", repo_url, repo_dir)
    repo = Repo.clone_from(repo_url, str(repo_dir))
    g = repo.git

    # Safe directory to avoid "detected dubious ownership" if container user differs
    try:
        _ = g.config("--global", "--add", "safe.directory", str(repo_dir))
    except Exception:
        pass

    # Configure identity
    user_name = os.getenv("GIT_USER_NAME", "Strands CodeOps Agent")
    user_email = os.getenv("GIT_USER_EMAIL", "codeops+bot@example.com")
    g.config("user.name", user_name)
    g.config("user.email", user_email)
    log.info("git_tools: git identity set to %s <%s>", user_name, user_email)

    # If token exists, rewrite origin URL to authed variant
    token = os.getenv("GITHUB_TOKEN")
    if token:
        authed = _authed_https_url(repo.remotes.origin.url, token)
        try:
            g.remote("set-url", "origin", authed)
            log.info("git_tools: origin URL set to authed https form")
        except Exception as e:
            log.warning("git_tools: failed to set authed origin URL: %s", e)

    # Checkout base and create feature branch
    log.info("git_tools: fetching origin")
    g.fetch("origin")
    log.info("git_tools: checking out base branch %s", base_branch)
    g.checkout(base_branch)
    log.info("git_tools: creating / switching to feature branch %s", branch_name)
    try:
        g.checkout("-b", branch_name)
    except GitCommandError:
        # branch already exists locally — switch to it
        g.checkout(branch_name)

    # Push the new branch upstream; capture detailed error text if it fails
    log.info("git_tools: pushing branch %s to origin", branch_name)
    try:
        repo.git.push("-u", "origin", branch_name)
        log.info("git_tools: push succeeded")
    except GitCommandError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        log.error("git_tools: push failed (stdout=%s, stderr=%s)", stdout, stderr)
        # Provide actionable hints
        hints = []
        if "Permission to" in stderr and "denied" in stderr:
            hints.append("GitHub denied permission to push. Check GITHUB_TOKEN scope and that it has write access to the repository.")
            hints.append("If this is not your repo or the token lacks rights, push to a fork instead (we can add a fork fallback).")
        if "The requested URL returned error: 403" in stderr:
            hints.append("HTTP 403 suggests missing/invalid token. Ensure docker compose passes GITHUB_TOKEN and that prepare_workspace set an authed origin URL.")
        raise RuntimeError("git push failed: " + "; ".join(hints) or stderr) from e

    # Parse owner/repo from URL (best-effort)
    owner = ""
    name = ""
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", repo.remotes.origin.url)
    if m:
        owner = m.group("owner")
        name = m.group("name")

    return {
        "repo_dir": str(repo_dir),
        "owner": owner,
        "repo_name": name,
        "branch": branch_name,
        "base": base_branch,
    }

@tool(name="commit_and_push", description="Commit staged changes and push to origin.")
def commit_and_push(repo_dir: str, commit_message: str) -> Dict:
    repo = Repo(repo_dir)
    g = repo.git

    # Stage everything (you can narrow this if needed)
    g.add("-A")

    if not repo.is_dirty():
        log.info("git_tools: nothing to commit")
        last = repo.head.commit.hexsha
        return {"last_commit": last, "changed": False}

    # Commit
    g.commit("-m", commit_message)
    last = repo.head.commit.hexsha
    log.info("git_tools: commit %s", last[:8])

    # Push
    try:
        repo.git.push()
        log.info("git_tools: push succeeded")
    except GitCommandError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        log.error("git_tools: push failed (stdout=%s, stderr=%s)", stdout, stderr)
        raise RuntimeError("git push failed: " + (stderr or stdout)) from e

    return {"last_commit": last, "changed": True}
