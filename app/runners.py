from __future__ import annotations
import os
import docker
from typing import Dict, Tuple


class DockerRunner:
    def __init__(self, image: str, workdir: str = "/workspace", env: Dict[str, str] | None = None,
                 cpu_shares: int | None = None, mem_limit: str | None = None, timeout_seconds: int = 1800):
        self.client = docker.from_env()
        self.image = image
        self.workdir = workdir
        self.env = env or {}
        self.cpu_shares = cpu_shares
        self.mem_limit = mem_limit
        self.timeout_seconds = timeout_seconds

    def run(self, host_repo_dir: str, command: str) -> Tuple[int, str]:
        container = None
        logs = ""
        try:
            try:
                self.client.images.pull(self.image)
            except Exception:
                pass
            container = self.client.containers.run(
                self.image,
                command,
                detach=True,
                working_dir=self.workdir,
                environment=self.env,
                volumes={host_repo_dir: {"bind": self.workdir, "mode": "rw"}},
                network=os.getenv("RUNNER_DOCKER_NETWORK"),
                cpu_shares=self.cpu_shares,
                mem_limit=self.mem_limit,
            )
            result = container.wait(timeout=self.timeout_seconds)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
            return int(result.get("StatusCode", 1)), logs
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
