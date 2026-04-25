"""Construcción de teclados inline para el bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.db.models import Order, Plan, Service


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🛍 Catálogo", "💰 Mi saldo"],
            ["📦 Mis pedidos", "❓ FAQ"],
            ["💬 Soporte", "ℹ️ Ayuda"],
        ],
        resize_keyboard=True,
    )


def payment_method_keyboard(plan_id: int, balance: float, price: float, currency: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if balance >= price:
        rows.append(
            [
                InlineKeyboardButton(
                    f"💰 Pagar con saldo ({balance:.2f} {currency})",
                    callback_data=f"pay:wallet:{plan_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "💳 Pagar con Yape/Plin/Transferencia",
                callback_data=f"pay:manual:{plan_id}",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton("⬅️ Cancelar", callback_data=f"back:plan:{plan_id}")]
    )
    return InlineKeyboardMarkup(rows)


def services_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for svc in services:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{svc.emoji} {svc.name}", callback_data=f"svc:{svc.id}"
                )
            ]
        )
    if not rows:
        rows.append(
            [InlineKeyboardButton("⛔ No hay servicios disponibles", callback_data="noop")]
        )
    return InlineKeyboardMarkup(rows)


def plans_keyboard(
    plans: list[Plan], currency: str, stock_counts: dict[int, int]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        stock = stock_counts.get(plan.id, 0)
        suffix = "🟢" if stock > 0 else "🔴"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{suffix} {plan.name} — {plan.price:.2f} {currency}",
                    callback_data=f"plan:{plan.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Volver", callback_data="back:services")])
    return InlineKeyboardMarkup(rows)


def plan_detail_keyboard(plan_id: int, has_stock: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_stock:
        rows.append(
            [InlineKeyboardButton("🛒 Comprar ahora", callback_data=f"buy:{plan_id}")]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔔 Avisarme cuando regrese", callback_data=f"wait:{plan_id}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("⬅️ Volver", callback_data=f"back:plan:{plan_id}")]
    )
    return InlineKeyboardMarkup(rows)


def renewal_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    """Botón de renovación 1-click usado en avisos de vencimiento."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Renovar ahora", callback_data=f"buy:{plan_id}")],
        ]
    )


def review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """5 estrellas + opción de saltar."""
    stars_row = [
        InlineKeyboardButton(f"{i}⭐", callback_data=f"review:{order_id}:{i}")
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup(
        [
            stars_row,
            [InlineKeyboardButton("Saltar", callback_data=f"review:{order_id}:0")],
        ]
    )


def order_pending_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Cancelar pedido", callback_data=f"order:cancel:{order_id}"
                )
            ]
        ]
    )


def admin_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Aprobar y entregar", callback_data=f"adm:approve:{order_id}"
                ),
                InlineKeyboardButton(
                    "🚫 Rechazar", callback_data=f"adm:reject:{order_id}"
                ),
            ]
        ]
    )
