from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentJob:
    id: str
    service: str
    action: str
    profile_name: str
    profile_pin: str
    account_reference: str
    account_email: str
    expires_at: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AgentJob":
        required = {
            "id", "service", "action", "profile_name", "profile_pin",
            "account_reference", "account_email", "expires_at",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Trabajo incompleto: {', '.join(sorted(missing))}")
        job = cls(**{field: str(payload[field]).strip() for field in required})
        if job.service != "netflix" or job.action != "create_profile":
            raise ValueError("Esta versión solo acepta netflix/create_profile")
        if not job.profile_name or len(job.profile_name) > 80:
            raise ValueError("Nombre de perfil inválido")
        if not (job.profile_pin.isdigit() and len(job.profile_pin) == 4):
            raise ValueError("El PIN debe contener exactamente 4 números")
        if job.account_email and ("@" not in job.account_email or len(job.account_email) > 255):
            raise ValueError("Correo de cuenta inválido")
        return job


@dataclass(frozen=True)
class JobResult:
    status: JobStatus
    message: str
    evidence: dict[str, Any] | None = None
