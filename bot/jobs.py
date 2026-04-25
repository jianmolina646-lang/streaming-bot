"""Tareas programadas: recordatorios y marcado de pedidos vencidos."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from telegram.ext import ContextTypes

from bot.db.database import session_scope
from bot.db.models import Order
from bot.keyboards import renewal_keyboard

log = logging.getLogger(__name__)


async def send_expiry_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Avisa al cliente cuando faltan ~3 días para que su suscripción venza."""
    now = datetime.utcnow()
    window_start = now + timedelta(hours=72 - 12)
    window_end = now + timedelta(hours=72 + 12)
    sent = 0
    with session_scope() as session:
        stmt = select(Order).where(
            Order.status == Order.STATUS_DELIVERED,
            Order.expires_at.isnot(None),
            Order.expires_at >= window_start,
            Order.expires_at <= window_end,
            Order.expiry_reminded_at.is_(None),
        )
        for order in session.scalars(stmt):
            try:
                days_left = max(1, (order.expires_at - now).days)
                txt = (
                    f"⏰ *Recordatorio de renovación*\n\n"
                    f"Tu suscripción a *{order.plan.service.name} — {order.plan.name}* "
                    f"vence en *{days_left} días*.\n\n"
                    "Toca el botón para renovar al instante. Si tienes saldo "
                    "se descuenta directo, si no te pediremos comprobante."
                )
                await context.bot.send_message(
                    order.user.telegram_id,
                    txt,
                    parse_mode="Markdown",
                    reply_markup=renewal_keyboard(order.plan_id),
                )
                order.expiry_reminded_at = now
                sent += 1
            except Exception:
                log.exception("Falló enviar recordatorio del pedido %s", order.id)
    if sent:
        log.info("Recordatorios enviados: %s", sent)


async def send_expiry_reminders_24h(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Avisa al cliente cuando falta ~1 día para que su suscripción venza."""
    now = datetime.utcnow()
    window_start = now + timedelta(hours=24 - 6)
    window_end = now + timedelta(hours=24 + 6)
    sent = 0
    with session_scope() as session:
        stmt = select(Order).where(
            Order.status == Order.STATUS_DELIVERED,
            Order.expires_at.isnot(None),
            Order.expires_at >= window_start,
            Order.expires_at <= window_end,
            Order.expiry_reminded_24h_at.is_(None),
        )
        for order in session.scalars(stmt):
            try:
                txt = (
                    "⚠️ *Tu suscripción vence mañana*\n\n"
                    f"Plan: *{order.plan.service.name} — {order.plan.name}*\n\n"
                    "Renueva ahora para no quedarte sin acceso. "
                    "Si tienes saldo, se descuenta al toque."
                )
                await context.bot.send_message(
                    order.user.telegram_id,
                    txt,
                    parse_mode="Markdown",
                    reply_markup=renewal_keyboard(order.plan_id),
                )
                order.expiry_reminded_24h_at = now
                sent += 1
            except Exception:
                log.exception(
                    "Falló enviar recordatorio 24h del pedido %s", order.id
                )
    if sent:
        log.info("Recordatorios 24h enviados: %s", sent)


async def mark_expired_and_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca como vencidos los pedidos cuya fecha de expiración ya pasó.

    - Cambia status a `expired`.
    - Notifica al cliente con un mensaje de "tu cuenta venció hoy".
    - Notifica a los admins con la lista de credenciales a cortar.
    """
    now = datetime.utcnow()
    settings = context.application.bot_data.get("settings")
    notified_clients = 0
    expired_summary: list[tuple[int, str, str, str, int]] = []
    # (order_id, plan_label, credential_first_line, username, telegram_id)

    with session_scope() as session:
        stmt = select(Order).where(
            Order.status == Order.STATUS_DELIVERED,
            Order.expires_at.isnot(None),
            Order.expires_at <= now,
            Order.expired_notified_at.is_(None),
        )
        for order in session.scalars(stmt):
            order.status = Order.STATUS_EXPIRED
            order.expired_notified_at = now

            # Aviso al cliente.
            try:
                await context.bot.send_message(
                    order.user.telegram_id,
                    f"❌ *Tu suscripción venció*\n\n"
                    f"Tu plan *{order.plan.service.name} — {order.plan.name}* (pedido "
                    f"#{order.id}) terminó hoy.\n\n"
                    "Toca el botón para renovar al instante.",
                    parse_mode="Markdown",
                    reply_markup=renewal_keyboard(order.plan_id),
                )
                notified_clients += 1
            except Exception:
                log.exception("No se pudo notificar al usuario %s", order.user.telegram_id)

            uname = order.user.username or order.user.full_name or str(order.user.telegram_id)
            cred_line = (order.delivered_credentials or "").split("\n")[0][:80]
            plan_label = f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}"
            expired_summary.append(
                (order.id, plan_label, cred_line, uname, order.user.telegram_id)
            )

    if not expired_summary:
        return

    if settings is None:
        log.warning("settings no disponible en bot_data; no se notifican admins")
        return

    lines = [
        f"⌛ *{len(expired_summary)} pedido(s) vencieron hoy* y necesitan corte:",
        "",
        "Da de baja el acceso en cada plataforma y usa "
        "`/markcut <id>` o `/cutall` cuando termines.",
        "",
    ]
    for order_id, plan_label, cred, uname, tg_id in expired_summary:
        lines.append(
            f"#{order_id} — @{uname} (TG `{tg_id}`)\n"
            f"  {plan_label}\n"
            f"  Credencial: `{cred}`\n"
        )
    text = "\n".join(lines)

    for admin_id in settings.admin_ids:
        try:
            for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
                await context.bot.send_message(admin_id, chunk, parse_mode="Markdown")
        except Exception:
            log.exception("No se pudo notificar al admin %s sobre vencimientos", admin_id)

    log.info(
        "Vencimiento procesado: %d pedidos, %d clientes notificados",
        len(expired_summary),
        notified_clients,
    )
