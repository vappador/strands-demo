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

def _redact(url: str) -> str:
    # Hide any tokens in logs (both standard and x-access-token styles)
    s = re.sub(r"(https?://)([^@/]+)@", r"\1***@", url)
    s = re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", s)
    return s

def _extract_clean_url(text: str) -> str:
    """
    Return a plausible git URL from 'text'.
    Accepts normal HTTPS or SSH urls; if 'text' contains extra fields
    (e.g., accidentally stringified objects), extract the first valid URL.
    """
    t = str(text or "").strip().strip("'").strip('"')
    # Directly acceptable?
    if t.startswith("https://") or t.startswith("git@"):
        return t

    # Try to find an https GitHub URL inside noisy text
    m = re.search(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", t)
    if m:
        return m.group(0)

    # Try to find an SSH GitHub URL
    m = re.search(r"git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", t)
    if m:
        return m.group(0)

    # As a last resort, if it looks like owner/repo, build https
    m = re.search(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b", t)
    if m and "github.com" in t:
        owner, name = m.group(1), m.group(2)
        return f"https://github.com/{owner}/{name}.git"

    raise ValueError(f"Could not parse a valid git URL from: {text!r}")

def _resolve_repo_url(passed_repo_url: str) -> str:
    """
    Resolve the repo URL with this priority:
    1) GIT_REMOTE_URL env (if set)
    2) repo_url argument (which may be a string, dict, or pydantic model)
    Then sanitize/extract a clean URL from the chosen value.
    """
    raw = os.getenv("GIT_REMOTE_URL") or passed_repo_url

    # If a model/dict was passed, try common fields
    if not isinstance(raw, (str, bytes)):
        # Attribute style: .url or .repo.url
        url = getattr(raw, "url", None)
        if not url:
            repo_obj = getattr(raw, "repo", None)
            if repo_obj is not None:
                url = getattr(repo_obj, "url", None)
        # Dict style: {"url": ...} or {"repo": {"url": ...}}
        if not url and isinstance(raw, dict):
            url = raw.get("url") or (raw.get("repo") or {}).get("url")
        raw = url if url else str(raw)

    return _extract_clean_url(raw)


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

    # Resolve & sanitize the URL (handles accidental object repr strings)
    clean_url = _resolve_repo_url(repo_url)
    log.info("git_tools: cloning %s → %s", _redact(clean_url), repo_dir)

    # Clone (start from default remote HEAD; we'll ensure base branch below)
    repo = Repo.clone_from(clean_url, str(repo_dir))
    g = repo.git

    # Safe directory to avoid "detected dubious ownership"
    try:
        g.config("--global", "--add", "safe.directory", str(repo_dir))
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
    try:
        current_origin_url = repo.remotes.origin.url
    except Exception:
        current_origin_url = clean_url  # best-effort

    if token and current_origin_url.startswith("https://"):
        authed = _authed_https_url(current_origin_url, token)
        try:
            g.remote("set-url", "origin", authed)
            log.info("git_tools: origin URL set to authed https form")
        except Exception as e:
            log.warning("git_tools: failed to set authed origin URL: %s", e)

    # Fetch & ensure local base branch exists (tracking origin/base_branch if needed)
    log.info("git_tools: fetching origin")
    g.fetch("origin")
    log.info("git_tools: checking out base branch %s", base_branch)
    try:
        # If local branch already exists
        g.rev_parse("--verify", base_branch)
        g.checkout(base_branch)
    except GitCommandError:
        # Create local branch tracking origin/base_branch
        g.checkout("-B", base_branch, f"origin/{base_branch}")

    # Create/switch to the feature branch
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
            hints.append("If this is not your repo or the token lacks rights, push to a fork instead (consider setting GIT_REMOTE_URL to your fork).")
        if "The requested URL returned error: 403" in stderr:
            hints.append("HTTP 403 suggests missing/invalid token. Ensure docker compose passes GITHUB_TOKEN and that prepare_workspace set an authed origin URL.")
        msg = "git push failed"
        if hints:
            msg += ": " + "; ".join(hints)
        else:
            msg += f": {stderr or stdout}"
        raise RuntimeError(msg) from e

    # Parse owner/repo from URL (best-effort)
    # Use the possibly-updated origin URL (could now be authed)
    try:
        origin_url = repo.remotes.origin.url
    except Exception:
        origin_url = clean_url

    owner = ""
    name = ""
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)", origin_url)
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
        last = getattr(repo.head, "commit", None)
        last_hex = last.hexsha if last else ""
        return {"last_commit": last_hex, "changed": False}

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
