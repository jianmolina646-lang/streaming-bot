"""Lista de espera: clientes que pidieron aviso cuando regrese el stock."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import WaitlistEntry


def add_entry(session: Session, user_id: int, plan_id: int) -> WaitlistEntry | None:
    """Añade entrada si no había una pendiente. Devuelve None si ya existía."""
    existing = session.scalar(
        select(WaitlistEntry).where(
            WaitlistEntry.user_id == user_id,
            WaitlistEntry.plan_id == plan_id,
            WaitlistEntry.notified_at.is_(None),
        )
    )
    if existing is not None:
        return None
    entry = WaitlistEntry(user_id=user_id, plan_id=plan_id)
    session.add(entry)
    session.flush()
    return entry


def pending_for_plan(session: Session, plan_id: int) -> list[WaitlistEntry]:
    return list(
        session.scalars(
            select(WaitlistEntry).where(
                WaitlistEntry.plan_id == plan_id,
                WaitlistEntry.notified_at.is_(None),
            )
        )
    )
