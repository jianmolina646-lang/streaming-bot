from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import AgentConfig
from .models import AgentJob, JobResult


class AgentApi:
    def __init__(self, config: AgentConfig):
        self.config = config

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.config.api_url}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": f"JhelizAgent/{self.config.name}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API respondió HTTP {exc.code}: {detail[:240]}") from exc

    def heartbeat(self) -> None:
        self._request("POST", "heartbeat", {
            "agent_name": self.config.name,
            "dry_run": self.config.dry_run,
            "capabilities": ["netflix.create_profile"],
        })

    def claim_next(self) -> AgentJob | None:
        payload = self._request("POST", "jobs/claim", {
            "agent_name": self.config.name,
            "capabilities": ["netflix.create_profile"],
        })
        return AgentJob.from_payload(payload["job"]) if payload.get("job") else None

    def finish(self, job: AgentJob, result: JobResult) -> None:
        self._request("POST", f"jobs/{job.id}/result", {
            "agent_name": self.config.name,
            "status": result.status.value,
            "message": result.message,
            "evidence": result.evidence or {},
        })
