"""Promoción automática de nivel VIP en función del gasto acumulado."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import Order, User


def lifetime_spent(session: Session, user_id: int) -> float:
    """Suma los importes pagados (precio - descuento) de los pedidos entregados."""
    rows = list(
        session.execute(
            select(Order.price, Order.discount_amount).where(
                Order.user_id == user_id,
                Order.status.in_((Order.STATUS_DELIVERED, Order.STATUS_EXPIRED)),
            )
        )
    )
    total = 0.0
    for price, discount in rows:
        total += max(0.0, float(price or 0.0) - float(discount or 0.0))
    return total


def target_vip_level(spent: float, threshold_1: float, threshold_2: float) -> int:
    if threshold_2 > 0 and spent >= threshold_2:
        return 2
    if threshold_1 > 0 and spent >= threshold_1:
        return 1
    return 0


def maybe_promote_vip(
    session: Session,
    user: User,
    threshold_1: float,
    threshold_2: float,
) -> int | None:
    """Sube al usuario a un nivel VIP superior si lo merece. Devuelve el nuevo nivel.

    Devuelve `None` si no hubo cambio (no baja niveles automáticamente).
    """
    spent = lifetime_spent(session, user.id)
    target = target_vip_level(spent, threshold_1, threshold_2)
    current = int(user.vip_level or 0)
    if target > current:
        user.vip_level = target
        return target
    return None
