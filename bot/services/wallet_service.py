"""Lógica del saldo / billetera del cliente."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import User, WalletTransaction


def get_balance(session: Session, user: User) -> float:
    return float(user.balance or 0.0)


def add_balance(
    session: Session,
    user: User,
    amount: float,
    kind: str = WalletTransaction.KIND_TOPUP,
    note: str | None = None,
    related_order_id: int | None = None,
) -> float:
    """Suma `amount` (puede ser negativo) al saldo del usuario y registra la transacción."""
    user.balance = float(user.balance or 0.0) + float(amount)
    session.add(
        WalletTransaction(
            user_id=user.id,
            amount=amount,
            kind=kind,
            note=note,
            related_order_id=related_order_id,
        )
    )
    session.flush()
    return user.balance


def set_balance(
    session: Session, user: User, new_balance: float, note: str | None = None
) -> float:
    diff = float(new_balance) - float(user.balance or 0.0)
    return add_balance(
        session, user, diff, kind=WalletTransaction.KIND_ADJUST, note=note
    )


def list_top_balances(session: Session, limit: int = 10) -> list[User]:
    stmt = (
        select(User)
        .where(User.balance > 0)
        .order_by(User.balance.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def list_transactions(session: Session, user_id: int, limit: int = 20) -> list[WalletTransaction]:
    stmt = (
        select(WalletTransaction)
        .where(WalletTransaction.user_id == user_id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
