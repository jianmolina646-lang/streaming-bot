"""API HTTP privada consumida por el agente local.

Escucha únicamente en loopback. TLS y límites externos deben aplicarse en el
proxy inverso. El token nunca se registra ni se guarda en texto plano.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from sqlalchemy import select

from bot.db.database import session_scope
from bot.db.models import AutomationAgent, AutomationJob
from bot.services.automation_service import decrypt_profile_pin
from config import Settings

log = logging.getLogger(__name__)
PREFIX = "/api/agent/v1"
MAX_BODY = 16 * 1024
RESULT_STATUSES = {
    AutomationJob.STATUS_RUNNING,
    AutomationJob.STATUS_NEEDS_ATTENTION,
    AutomationJob.STATUS_SUCCEEDED,
    AutomationJob.STATUS_FAILED,
}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 80:
        raise ValueError("agent_name inválido")
    return name


class AgentRequestHandler(BaseHTTPRequestHandler):
    server: "AgentHttpServer"

    def log_message(self, format: str, *args) -> None:
        log.info("Agent API %s - %s", self.client_address[0], format % args)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length inválido") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("Cuerpo demasiado grande")
        if not length:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("El cuerpo debe ser un objeto JSON")
        return value

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.settings.agent_api_token}"
        return bool(self.server.settings.agent_api_token) and hmac.compare_digest(
            supplied, expected
        )

    def do_GET(self) -> None:
        if self.path == f"{PREFIX}/health":
            self._json(HTTPStatus.OK, {"status": "ok", "mode": "private"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            payload = self._payload()
            if self.path == f"{PREFIX}/heartbeat":
                response = self._heartbeat(payload)
            elif self.path == f"{PREFIX}/jobs/claim":
                response = self._claim(payload)
            elif self.path.startswith(f"{PREFIX}/jobs/") and self.path.endswith("/result"):
                job_id = self.path[len(f"{PREFIX}/jobs/") : -len("/result")].strip("/")
                response = self._result(job_id, payload)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(HTTPStatus.OK, response)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            log.exception("Error interno en Agent API")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    def _agent(self, session, payload: dict[str, Any]) -> AutomationAgent:
        name = _safe_name(payload.get("agent_name"))
        hashed = _token_hash(self.server.settings.agent_api_token)
        agent = session.scalar(
            select(AutomationAgent).where(AutomationAgent.token_hash == hashed)
        )
        if agent and agent.name != name:
            raise ValueError("El token pertenece a otro agente")
        if not agent:
            agent = AutomationAgent(name=name, token_hash=hashed)
            session.add(agent)
            session.flush()
        if not agent.is_active:
            raise ValueError("Agente desactivado")
        return agent

    def _heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        with session_scope() as session:
            agent = self._agent(session, payload)
            agent.last_seen_at = datetime.utcnow()
            agent.dry_run = bool(payload.get("dry_run", True))
            capabilities = payload.get("capabilities", [])
            agent.capabilities = json.dumps(capabilities[:20] if isinstance(capabilities, list) else [])
            return {"status": "ok", "agent_id": agent.id, "dry_run": agent.dry_run}

    def _claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        with session_scope() as session:
            agent = self._agent(session, payload)
            agent.last_seen_at = datetime.utcnow()
            job = session.scalar(
                select(AutomationJob)
                .where(
                    AutomationJob.status == AutomationJob.STATUS_QUEUED,
                    AutomationJob.agent_id.is_(None),
                    AutomationJob.expires_at > datetime.utcnow(),
                )
                .order_by(AutomationJob.created_at.asc())
                .limit(1)
            )
            if not job:
                return {"job": None}
            job.agent_id = agent.id
            job.status = AutomationJob.STATUS_CLAIMED
            job.claimed_at = datetime.utcnow()
            job.attempts += 1
            return {"job": {
                "id": job.id,
                "service": job.service,
                "action": job.action,
                "profile_name": job.profile_name,
                "profile_pin": decrypt_profile_pin(
                    job, self.server.settings.agent_encryption_key
                ),
                "account_reference": str(job.stock_item_id),
                "expires_at": job.expires_at.isoformat() + "Z",
            }}

    def _result(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not job_id or len(job_id) > 36:
            raise ValueError("ID de trabajo inválido")
        status = str(payload.get("status", "")).strip()
        if status not in RESULT_STATUSES:
            raise ValueError("Estado de resultado inválido")
        with session_scope() as session:
            agent = self._agent(session, payload)
            job = session.get(AutomationJob, job_id)
            if not job or job.agent_id != agent.id:
                raise ValueError("Trabajo no asignado a este agente")
            job.status = status
            job.result_message = str(payload.get("message", ""))[:1000]
            evidence = payload.get("evidence", {})
            job.evidence = json.dumps(evidence if isinstance(evidence, dict) else {})
            if status in {AutomationJob.STATUS_SUCCEEDED, AutomationJob.STATUS_FAILED}:
                job.finished_at = datetime.utcnow()
            return {"status": "ok", "job_id": job.id}


class AgentHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, settings: Settings):
        self.settings = settings
        super().__init__(address, AgentRequestHandler)


def start_agent_api(settings: Settings) -> AgentHttpServer | None:
    if not settings.agent_api_token:
        log.warning("Agent API desactivada: falta AGENT_API_TOKEN")
        return None
    if not settings.agent_encryption_key:
        raise RuntimeError("AGENT_ENCRYPTION_KEY es obligatoria para Agent API")
    server = AgentHttpServer((settings.agent_api_host, settings.agent_api_port), settings)
    Thread(target=server.serve_forever, name="agent-api", daemon=True).start()
    log.info(
        "Agent API escuchando en http://%s:%s",
        settings.agent_api_host,
        settings.agent_api_port,
    )
    return server
