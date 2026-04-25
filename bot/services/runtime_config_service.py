"""Configuración runtime (sobreescribe valores del .env sin reiniciar)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from bot.db.database import session_scope
from bot.db.models import RuntimeConfig

KEY_MAINTENANCE = "maintenance_mode"
KEY_PAYMENT = "payment_instructions"
KEY_SHOP_NAME = "shop_name"
KEY_PROMO = "promo_text"


def get(session: Session, key: str, default: str | None = None) -> str | None:
    item = session.get(RuntimeConfig, key)
    return item.value if item is not None else default


def set_value(session: Session, key: str, value: str) -> None:
    item = session.get(RuntimeConfig, key)
    if item is None:
        item = RuntimeConfig(key=key, value=value)
        session.add(item)
    else:
        item.value = value
    session.flush()


def delete(session: Session, key: str) -> None:
    item = session.get(RuntimeConfig, key)
    if item is not None:
        session.delete(item)
        session.flush()


# ---------- helpers de alto nivel ----------

def is_maintenance() -> bool:
    with session_scope() as s:
        return get(s, KEY_MAINTENANCE, "0") == "1"


def get_payment_instructions(default: str) -> str:
    with session_scope() as s:
        return get(s, KEY_PAYMENT, default) or default


def get_shop_name(default: str) -> str:
    with session_scope() as s:
        return get(s, KEY_SHOP_NAME, default) or default


def get_promo() -> str | None:
    with session_scope() as s:
        return get(s, KEY_PROMO, None)
