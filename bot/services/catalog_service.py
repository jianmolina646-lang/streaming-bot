"""Lógica de negocio del catálogo y stock."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bot.db.models import Plan, Service, StockItem


def list_active_services(session: Session) -> list[Service]:
    stmt = select(Service).where(Service.is_active.is_(True)).order_by(Service.name)
    return list(session.scalars(stmt))


def get_service(session: Session, service_id: int) -> Service | None:
    return session.get(Service, service_id)


def list_active_plans(session: Session, service_id: int) -> list[Plan]:
    stmt = (
        select(Plan)
        .where(Plan.service_id == service_id, Plan.is_active.is_(True))
        .order_by(Plan.price)
    )
    return list(session.scalars(stmt))


def get_plan(session: Session, plan_id: int) -> Plan | None:
    return session.get(Plan, plan_id)


def stock_count_for_plans(session: Session, plan_ids: list[int]) -> dict[int, int]:
    if not plan_ids:
        return {}
    stmt = (
        select(StockItem.plan_id, func.count(StockItem.id))
        .where(StockItem.plan_id.in_(plan_ids), StockItem.is_sold.is_(False))
        .group_by(StockItem.plan_id)
    )
    return {pid: count for pid, count in session.execute(stmt).all()}


def take_stock(session: Session, plan_id: int) -> StockItem | None:
    """Reserva (marca como vendido) un item de stock disponible."""
    stmt = (
        select(StockItem)
        .where(StockItem.plan_id == plan_id, StockItem.is_sold.is_(False))
        .order_by(StockItem.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    item = session.scalars(stmt).first()
    if item is None:
        return None
    item.is_sold = True
    session.flush()
    return item


def add_service(session: Session, name: str, emoji: str, description: str | None) -> Service:
    svc = Service(name=name, emoji=emoji, description=description)
    session.add(svc)
    session.flush()
    return svc


def add_plan(
    session: Session,
    service_id: int,
    name: str,
    duration_days: int,
    price: float,
    description: str | None,
) -> Plan:
    plan = Plan(
        service_id=service_id,
        name=name,
        duration_days=duration_days,
        price=price,
        description=description,
    )
    session.add(plan)
    session.flush()
    return plan


def add_stock_lines(session: Session, plan_id: int, lines: list[str]) -> int:
    added = 0
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        session.add(StockItem(plan_id=plan_id, credentials=text))
        added += 1
    session.flush()
    return added
