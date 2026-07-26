"""Cliente mínimo de Mail Control: únicamente reclama códigos recientes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
import time

from .config import AgentConfig
from .models import AgentJob


class MailControlClient:
    def __init__(self, config: AgentConfig):
        self.url = config.mail_control_url
        self.token = config.mail_control_token

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def claim_code(self, job: AgentJob, *, not_before: datetime) -> str | None:
        if not self.enabled or not job.account_email:
            return None
        payload = json.dumps({
            "job_id": job.id,
            "account_email": job.account_email,
            "service": job.service,
            "not_before": not_before.astimezone(timezone.utc).isoformat(),
        }).encode()
        request = urllib.request.Request(
            f"{self.url}/codes/claim",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare bloquea la firma predeterminada Python-urllib (1010).
                # La seguridad real sigue siendo el token Bearer de 256 bits.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36 JhelizAgent/1.0"
                ),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mail Control respondió HTTP {exc.code}: {detail[:200]}") from exc
        return str(data["code"]) if data.get("status") == "found" else None

    def wait_for_code(
        self,
        job: AgentJob,
        *,
        not_before: datetime,
        timeout_seconds: int,
    ) -> str | None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            code = self.claim_code(job, not_before=not_before)
            if code:
                return code
            time.sleep(5)
        return None
