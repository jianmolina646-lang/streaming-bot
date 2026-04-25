"""Inicialización del motor y sesiones SQLAlchemy."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bot.db.models import Base

log = logging.getLogger(__name__)

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


# Columnas añadidas en versiones posteriores. Si la BD ya existe sin ellas,
# las añadimos con ALTER TABLE para no perder los datos.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "orders": [
        ("delivered_at", "DATETIME"),
        ("expires_at", "DATETIME"),
        ("expiry_reminded_at", "DATETIME"),
        ("expired_notified_at", "DATETIME"),
        ("cut_at", "DATETIME"),
        ("review_requested_at", "DATETIME"),
        ("payment_method", "VARCHAR(16) DEFAULT 'manual'"),
        ("discount_amount", "FLOAT DEFAULT 0.0"),
        ("coupon_id", "INTEGER"),
    ],
    "users": [
        ("balance", "FLOAT DEFAULT 0.0"),
        ("ref_code", "VARCHAR(16)"),
        ("referred_by_id", "INTEGER"),
        ("vip_level", "INTEGER DEFAULT 0"),
        ("internal_note", "TEXT"),
    ],
    "stock": [
        ("tag", "VARCHAR(32)"),
    ],
}


def _apply_lightweight_migrations(engine: Engine) -> None:
    """Añade columnas que falten en tablas existentes (solo SQLite-friendly)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, sqltype in cols:
                if name in existing:
                    continue
                stmt = text(f'ALTER TABLE {table} ADD COLUMN {name} {sqltype}')
                log.info("Migración: %s", stmt)
                conn.execute(stmt)


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    _engine = create_engine(database_url, future=True, echo=False)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    _apply_lightweight_migrations(_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Llama a init_db() primero")
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexto que abre una sesión y hace commit/rollback automático."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
