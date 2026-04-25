"""Lógica de FAQ / soporte automatizado."""
from __future__ import annotations

import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.db.models import Faq


def add_faq(session: Session, question: str, answer: str, keywords: str | None) -> Faq:
    faq = Faq(question=question.strip(), answer=answer.strip(), keywords=keywords)
    session.add(faq)
    session.flush()
    return faq


def list_active_faqs(session: Session) -> list[Faq]:
    stmt = select(Faq).where(Faq.is_active.is_(True)).order_by(Faq.id)
    return list(session.scalars(stmt))


def list_all_faqs(session: Session) -> list[Faq]:
    return list(session.scalars(select(Faq).order_by(Faq.id)))


def delete_faq(session: Session, faq_id: int) -> bool:
    faq = session.get(Faq, faq_id)
    if faq is None:
        return False
    session.delete(faq)
    return True


def find_matching_faq(session: Session, text: str) -> Faq | None:
    """Busca un FAQ cuyas palabras clave aparezcan en el texto del usuario."""
    if not text:
        return None
    norm = text.lower()
    faqs = list_active_faqs(session)
    best: Faq | None = None
    best_score = 0
    for faq in faqs:
        kw = (faq.keywords or "").lower()
        # Cada palabra separada por coma cuenta. Una coincidencia ya basta.
        words = [w.strip() for w in re.split(r"[,;]+", kw) if w.strip()]
        if not words:
            continue
        score = sum(1 for w in words if w in norm)
        if score > best_score:
            best_score = score
            best = faq
    return best
