# app/runners.py
from __future__ import annotations
import os
from typing import Dict, Tuple

import docker
from docker.errors import APIError


class DockerRunner:
    """
    Launch short-lived containers via the host Docker daemon and bind-mount the repo.

    Mapping rules (Docker Desktop macOS/Windows):
      - WORKSPACE_DIR (container base), e.g. "/workspace/jobs"
      - HOST_WORKSPACE_DIR (host base), e.g. "/Users/you/project/jobs"
      Any path under WORKSPACE_DIR (including WORKSPACE_DIR itself) is remapped to the
      HOST_WORKSPACE_DIR before creating the bind mount.
    """

    def __init__(
        self,
        image: str,
        workdir: str = "/workspace",
        env: Dict[str, str] | None = None,
        cpu_shares: int | None = None,
        mem_limit: str | None = None,
        timeout_seconds: int = 1800,
    ):
        self.client = docker.from_env()
        self.image = image
        self.workdir = workdir
        self.env = env or {}
        self.cpu_shares = cpu_shares
        self.mem_limit = mem_limit
        self.timeout_seconds = timeout_seconds

        # Bases for mapping
        self.cbase = os.getenv("WORKSPACE_DIR", "/workspace/jobs")
        self.hbase = os.getenv("HOST_WORKSPACE_DIR")  # required on Docker Desktop if using container paths

        # Controls
        self.should_pull = os.getenv("RUNNER_IMAGE_PULL", "1") != "0"
        self.network = os.getenv("RUNNER_DOCKER_NETWORK") or None
        self.debug = os.getenv("RUNNER_DEBUG") == "1"

    # ----------------------------- Path Mapping ------------------------------

    def _to_host_path(self, path: str) -> str:
        """
        Accepts container or host path; returns a host path suitable for bind mounts.
        IMPORTANT: We match the container base FIRST so that "/workspace/jobs" itself
        is remapped (previous bug).
        """
        if not path:
            raise ValueError("Empty path given to DockerRunner._to_host_path")

        rp = os.path.realpath(path)
        cbase = os.path.realpath(self.cbase) if self.cbase else None
        hbase = os.path.realpath(self.hbase) if self.hbase else None

        # Case A: It's under the container workspace (or equals it) -> REMAP
        if cbase and (rp == cbase or rp.startswith(cbase + os.sep)):
            if not hbase:
                raise ValueError(
                    f"Path '{rp}' is under container workspace '{self.cbase}', "
                    f"but HOST_WORKSPACE_DIR is not set. Set HOST_WORKSPACE_DIR to the "
                    f"matching host base (e.g., /Users/you/project/jobs)."
                )
            suffix = os.path.relpath(rp, cbase)  # "" when equal to cbase
            host_path = os.path.realpath(os.path.join(hbase, suffix)) if suffix != "." else hbase
            if self.debug:
                print(f"[DockerRunner] map container→host: {rp}  ==>  {host_path}")
            return host_path

        # Case B: Treat as a host path (Linux or already-host absolute path)
        if self.debug:
            print(f"[DockerRunner] treat as host path: {rp}")
        return rp

    # ------------------------------- Runner ----------------------------------

    def run(self, repo_dir: str, command: str) -> Tuple[int, str]:
        """
        Run command in a fresh container with repo_dir bind-mounted to self.workdir.
        """
        container = None
        logs = ""

        if self.should_pull:
            try:
                self.client.images.pull(self.image)
            except Exception:
                pass

        try:
            host_repo_dir = self._to_host_path(repo_dir)

            if self.debug:
                print(f"[DockerRunner] image={self.image}")
                print(f"[DockerRunner] workdir={self.workdir}")
                print(f"[DockerRunner] bind source={host_repo_dir}")
                print(f"[DockerRunner] network={self.network!r}")

            container = self.client.containers.run(
                self.image,
                command,
                detach=True,
                working_dir=self.workdir,
                environment=self.env,
                volumes={host_repo_dir: {"bind": self.workdir, "mode": "rw"}},
                network=self.network,
                cpu_shares=self.cpu_shares,
                mem_limit=self.mem_limit,
            )

            result = container.wait(timeout=self.timeout_seconds)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
            status = int(result.get("StatusCode", 1))
            return status, logs

        except APIError as e:
            explanation = getattr(e, "explanation", "") or str(e)
            if "is not shared from the host" in explanation or "mounts denied" in explanation:
                logs += (
                    "\n\n[HINT] Docker Desktop: path not shared from host.\n"
                    " - Ensure your HOST_WORKSPACE_DIR is under a shared root (e.g., /Users on macOS).\n"
                    " - Docker Desktop → Settings → Resources → File sharing: add the parent dir.\n"
                    f" - WORKSPACE_DIR={self.cbase}\n"
                    f" - HOST_WORKSPACE_DIR={self.hbase}\n"
                    f" - Resolved bind source={host_repo_dir if 'host_repo_dir' in locals() else '(n/a)'}\n"
                )
            raise
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
