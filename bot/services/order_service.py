"""Lógica de pedidos."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from bot.db.models import Order, Plan, User


def get_or_create_user(
    session: Session,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
) -> User:
    user = session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        session.add(user)
        session.flush()
    else:
        # Mantener username/nombre actualizados.
        if username and user.username != username:
            user.username = username
        if full_name and user.full_name != full_name:
            user.full_name = full_name
    return user


def create_order(session: Session, user: User, plan: Plan) -> Order:
    order = Order(
        user_id=user.id,
        plan_id=plan.id,
        price=plan.price,
        status=Order.STATUS_PENDING_PAYMENT,
    )
    session.add(order)
    session.flush()
    return order


def get_order(session: Session, order_id: int) -> Order | None:
    stmt = (
        select(Order)
        .options(joinedload(Order.plan).joinedload(Plan.service), joinedload(Order.user))
        .where(Order.id == order_id)
    )
    return session.scalar(stmt)


def list_user_orders(session: Session, user_id: int, limit: int = 10) -> list[Order]:
    stmt = (
        select(Order)
        .options(joinedload(Order.plan).joinedload(Plan.service))
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def list_pending_orders(session: Session, limit: int = 20) -> list[Order]:
    stmt = (
        select(Order)
        .options(joinedload(Order.plan).joinedload(Plan.service), joinedload(Order.user))
        .where(Order.status == Order.STATUS_AWAITING_REVIEW)
        .order_by(Order.created_at.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
