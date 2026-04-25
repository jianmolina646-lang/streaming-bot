"""Garantías / tickets de soporte vinculados a un pedido."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from bot.db.models import WarrantyTicket


def open_ticket(
    session: Session, user_id: int, order_id: int, message: str | None
) -> WarrantyTicket:
    t = WarrantyTicket(user_id=user_id, order_id=order_id, message=message)
    session.add(t)
    session.flush()
    return t


def list_open(session: Session, limit: int = 50) -> list[WarrantyTicket]:
    return list(
        session.scalars(
            select(WarrantyTicket)
            .where(WarrantyTicket.status == WarrantyTicket.STATUS_OPEN)
            .order_by(WarrantyTicket.created_at)
            .limit(limit)
        )
    )


def get_ticket(session: Session, ticket_id: int) -> WarrantyTicket | None:
    return session.get(WarrantyTicket, ticket_id)


def resolve(session: Session, ticket_id: int, note: str | None = None) -> bool:
    t = session.get(WarrantyTicket, ticket_id)
    if t is None:
        return False
    t.status = WarrantyTicket.STATUS_RESOLVED
    t.resolved_at = datetime.utcnow()
    if note:
        t.admin_note = note
    session.flush()
    return True
