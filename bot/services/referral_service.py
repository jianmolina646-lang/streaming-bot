"""Sistema de referidos: code único por usuario y comisiones."""
from __future__ import annotations

import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bot.db.models import Order, User, WalletTransaction
from bot.services.wallet_service import add_balance

# Comisión que recibe el referidor cuando su referido hace su PRIMER pedido entregado.
# Porcentaje del precio final del pedido.
REFERRAL_COMMISSION_PCT = 10.0


def _new_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "REF" + "".join(secrets.choice(alphabet) for _ in range(6))


def ensure_ref_code(session: Session, user: User) -> str:
    """Devuelve el código de referido del usuario, creándolo si no existe."""
    if user.ref_code:
        return user.ref_code
    while True:
        code = _new_code()
        exists = session.scalar(select(User).where(User.ref_code == code))
        if exists is None:
            user.ref_code = code
            session.flush()
            return code


def get_user_by_ref_code(session: Session, code: str) -> User | None:
    return session.scalar(select(User).where(User.ref_code == code.upper().strip()))


def attach_referral(session: Session, new_user: User, ref_code: str) -> bool:
    """Marca a `new_user` como referido de quien tiene `ref_code`. Solo una vez."""
    if new_user.referred_by_id is not None:
        return False
    referrer = get_user_by_ref_code(session, ref_code)
    if referrer is None or referrer.id == new_user.id:
        return False
    new_user.referred_by_id = referrer.id
    session.flush()
    return True


def count_referrals(session: Session, user_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(User.id)).where(User.referred_by_id == user_id)
        )
        or 0
    )


def total_commission_earned(session: Session, user_id: int) -> float:
    val = session.scalar(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0.0)).where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.kind == WalletTransaction.KIND_REFERRAL,
        )
    )
    return float(val or 0.0)


def maybe_pay_commission(session: Session, order: Order) -> float:
    """Paga comisión al referidor SI el comprador es referido y este es su primer pedido entregado."""
    user = order.user
    if user.referred_by_id is None:
        return 0.0
    # Solo en su primer pedido entregado.
    delivered_count = session.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == user.id,
            Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]),
        )
    )
    if (delivered_count or 0) > 1:
        return 0.0
    referrer = session.get(User, user.referred_by_id)
    if referrer is None:
        return 0.0
    final_price = max(0.0, order.price - (order.discount_amount or 0.0))
    commission = round(final_price * (REFERRAL_COMMISSION_PCT / 100.0), 2)
    if commission <= 0:
        return 0.0
    add_balance(
        session,
        referrer,
        commission,
        kind=WalletTransaction.KIND_REFERRAL,
        note=f"Comisión {REFERRAL_COMMISSION_PCT:.0f}% por referido pedido #{order.id}",
        related_order_id=order.id,
    )
    return commission
