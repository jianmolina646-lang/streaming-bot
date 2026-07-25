from __future__ import annotations

import signal
import time

from jheliz_agent.client import AgentApi
from jheliz_agent.config import AgentConfig
from jheliz_agent.netflix import NetflixAdapter


def run() -> None:
    config = AgentConfig.from_env()
    api = AgentApi(config)
    adapter = NetflixAdapter(config)
    running = True

    def stop(*_args):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    mode = "SIMULACIÓN" if config.dry_run else "REAL BLOQUEADO"
    print(f"Jheliz Agent conectado como {config.name} · modo {mode}", flush=True)

    last_heartbeat = 0.0
    while running:
        try:
            now = time.monotonic()
            if now - last_heartbeat >= 30:
                api.heartbeat()
                last_heartbeat = now
            job = api.claim_next()
            if job:
                print(f"Trabajo {job.id}: {job.action} para {job.profile_name}", flush=True)
                api.finish(job, adapter.execute(job))
        except Exception as exc:
            print(f"Agente temporalmente desconectado: {exc}", flush=True)
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    run()
