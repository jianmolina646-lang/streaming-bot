"""Navegación del catálogo de servicios y planes."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.database import session_scope
from bot.db.models import Order
from bot.keyboards import plan_detail_keyboard, plans_keyboard, services_keyboard
from bot.services.catalog_service import (
    get_plan,
    get_service,
    list_active_plans,
    list_active_services,
    stock_count_for_plans,
)
from bot.services.runtime_config_service import get_promo
from bot.services.order_service import get_or_create_user
from bot.services.waitlist_service import add_entry as waitlist_add
from config import Settings


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        services = list_active_services(session)
        markup = services_keyboard(services)
    promo = get_promo()
    intro = ""
    if promo:
        intro = f"📣 *{promo}*\n\n"
    text = f"{intro}🛍 *Catálogo de servicios*\n\nElige una plataforma:"
    if update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )
    elif update.message is not None:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def cb_waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `wait:<plan_id>` — añade al cliente a la lista de espera."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        await query.answer() if query else None
        return
    await query.answer()
    try:
        plan_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    tg_user = update.effective_user
    with session_scope() as session:
        user = get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.full_name
        )
        plan = get_plan(session, plan_id)
        if plan is None:
            await query.edit_message_text("Plan no encontrado.")
            return
        plan_label = f"{plan.service.emoji} {plan.service.name} — {plan.name}"
        entry = waitlist_add(session, user.id, plan_id)
    if entry is None:
        await query.edit_message_text(
            f"🔔 Ya estabas en la lista de espera de *{plan_label}*. "
            "Te avisaré cuando regrese el stock.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            f"🔔 Listo. Te avisaré apenas vuelva el stock de *{plan_label}*.",
            parse_mode="Markdown",
        )


async def show_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        service_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    settings = _settings(context)
    with session_scope() as session:
        service = get_service(session, service_id)
        if service is None:
            await query.edit_message_text("Servicio no encontrado.")
            return
        plans = list_active_plans(session, service_id)
        counts = stock_count_for_plans(session, [p.id for p in plans])
        markup = plans_keyboard(plans, settings.currency, counts)
        desc = service.description or "Elige uno de los planes disponibles."
        text = f"{service.emoji} *{service.name}*\n\n{desc}"
    await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")


async def show_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        plan_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    settings = _settings(context)
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await query.edit_message_text("Plan no encontrado.")
            return
        counts = stock_count_for_plans(session, [plan.id])
        stock = counts.get(plan.id, 0)
        markup = plan_detail_keyboard(plan.id, has_stock=stock > 0)
        text = (
            f"{plan.service.emoji} *{plan.service.name} — {plan.name}*\n\n"
            f"💵 Precio: *{plan.price:.2f} {settings.currency}*\n"
            f"⏳ Duración: *{plan.duration_days} días*\n"
            f"📦 Disponibles: *{stock}*\n"
        )
        if plan.description:
            text += f"\n{plan.description}\n"
    await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")


async def back_to_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_catalog(update, context)
