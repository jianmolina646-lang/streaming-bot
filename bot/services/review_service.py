"""Servicios para reseñas (calificación post-entrega)."""
from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from bot.db.models import Review


def add_review(
    session: Session, order_id: int, user_id: int, rating: int, comment: str | None
) -> Review:
    rating = max(1, min(5, int(rating)))
    review = Review(
        order_id=order_id, user_id=user_id, rating=rating, comment=comment
    )
    session.add(review)
    session.flush()
    return review


def get_review_for_order(session: Session, order_id: int) -> Review | None:
    return session.scalar(select(Review).where(Review.order_id == order_id))


def list_recent_reviews(session: Session, limit: int = 20) -> list[Review]:
    return list(
        session.scalars(select(Review).order_by(desc(Review.created_at)).limit(limit))
    )


def average_rating(session: Session) -> tuple[float, int]:
    avg = session.scalar(select(func.avg(Review.rating)))
    cnt = session.scalar(select(func.count(Review.id)))
    return float(avg or 0.0), int(cnt or 0)
