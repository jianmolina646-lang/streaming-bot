"""Servicios para cupones de descuento."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import Coupon


def get_coupon_by_code(session: Session, code: str) -> Coupon | None:
    return session.scalar(select(Coupon).where(Coupon.code == code.upper()))


def add_coupon(
    session: Session,
    code: str,
    discount_percent: float = 0.0,
    discount_amount: float = 0.0,
    max_uses: int = 0,
    expires_at: datetime | None = None,
) -> Coupon:
    coupon = Coupon(
        code=code.upper().strip(),
        discount_percent=max(0.0, float(discount_percent)),
        discount_amount=max(0.0, float(discount_amount)),
        max_uses=max(0, int(max_uses)),
        uses=0,
        expires_at=expires_at,
        is_active=True,
    )
    session.add(coupon)
    session.flush()
    return coupon


def list_coupons(session: Session, only_active: bool = False) -> list[Coupon]:
    stmt = select(Coupon).order_by(Coupon.created_at.desc())
    if only_active:
        stmt = stmt.where(Coupon.is_active.is_(True))
    return list(session.scalars(stmt))


def is_valid(coupon: Coupon) -> bool:
    if not coupon.is_active:
        return False
    if coupon.max_uses and coupon.uses >= coupon.max_uses:
        return False
    if coupon.expires_at is not None and coupon.expires_at <= datetime.utcnow():
        return False
    return True


def compute_discount(coupon: Coupon, price: float) -> float:
    """Devuelve el monto de descuento aplicado a `price`."""
    if not is_valid(coupon):
        return 0.0
    if coupon.discount_percent > 0:
        d = price * (coupon.discount_percent / 100.0)
    else:
        d = coupon.discount_amount
    return max(0.0, min(price, round(d, 2)))


def consume(session: Session, coupon: Coupon) -> None:
    coupon.uses = (coupon.uses or 0) + 1
    if coupon.max_uses and coupon.uses >= coupon.max_uses:
        coupon.is_active = False
    session.flush()


def delete_coupon(session: Session, coupon_id: int) -> bool:
    coupon = session.get(Coupon, coupon_id)
    if coupon is None:
        return False
    coupon.is_active = False
    session.flush()
    return True
