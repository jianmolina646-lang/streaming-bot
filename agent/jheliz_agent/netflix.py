from __future__ import annotations

from .config import AgentConfig
from .models import AgentJob, JobResult, JobStatus


class NetflixAdapter:
    """Adaptador seguro inicial.

    El modo real se habilitará únicamente después de validar emparejamiento,
    aislamiento por revendedor y recuperación de códigos. Hasta entonces el
    agente confirma el trabajo sin abrir ni modificar Netflix.
    """

    def __init__(self, config: AgentConfig):
        self.config = config

    def execute(self, job: AgentJob) -> JobResult:
        if not self.config.dry_run:
            return JobResult(
                status=JobStatus.NEEDS_ATTENTION,
                message=(
                    "El adaptador real todavía está bloqueado por seguridad. "
                    "Activa primero el flujo validado de prueba."
                ),
            )
        return JobResult(
            status=JobStatus.SUCCEEDED,
            message="Simulación completada; no se modificó ninguna cuenta.",
            evidence={
                "dry_run": True,
                "service": job.service,
                "action": job.action,
                "profile_name": job.profile_name,
                "pin_length": len(job.profile_pin),
                "account_reference": job.account_reference,
            },
        )
