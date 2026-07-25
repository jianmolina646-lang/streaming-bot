"""Cola segura para trabajos que serán procesados por el agente local."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import AutomationJob, Order, StockItem

AUTOMATION_STOCK_TAG = "agent-netflix"


def is_automation_stock(item: StockItem | None) -> bool:
    return bool(item and (item.tag or "").strip().lower() == AUTOMATION_STOCK_TAG)


def default_profile_name(order: Order) -> str:
    raw = (order.user.full_name or order.user.username or f"Cliente {order.user_id}").strip()
    return raw.split()[0][:80] or f"Cliente {order.user_id}"


def generate_profile_pin() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def create_profile_job(
    session: Session,
    *,
    order: Order,
    stock_item: StockItem,
    encryption_key: str,
    profile_name: str | None = None,
    profile_pin: str | None = None,
) -> AutomationJob:
    existing = session.scalar(select(AutomationJob).where(AutomationJob.order_id == order.id))
    if existing:
        return existing
    if not is_automation_stock(stock_item):
        raise ValueError("El stock no está habilitado para el agente Netflix")
    name = (profile_name or default_profile_name(order)).strip()
    pin = (profile_pin or generate_profile_pin()).strip()
    if not name or len(name) > 80:
        raise ValueError("Nombre de perfil inválido")
    if not (pin.isdigit() and len(pin) == 4):
        raise ValueError("El PIN debe contener exactamente 4 números")
    job = AutomationJob(
        id=str(uuid.uuid4()),
        order_id=order.id,
        stock_item_id=stock_item.id,
        service="netflix",
        action="create_profile",
        profile_name=name,
        profile_pin_hash=hashlib.sha256(pin.encode()).hexdigest(),
        profile_pin_encrypted=Fernet(encryption_key.encode()).encrypt(pin.encode()).decode(),
        status=AutomationJob.STATUS_QUEUED,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    order.status = Order.STATUS_APPROVED
    order.admin_note = "Preparación automática de perfil en cola."
    session.add(job)
    session.flush()
    return job


def decrypt_profile_pin(job: AutomationJob, encryption_key: str) -> str:
    return Fernet(encryption_key.encode()).decrypt(job.profile_pin_encrypted.encode()).decode()
