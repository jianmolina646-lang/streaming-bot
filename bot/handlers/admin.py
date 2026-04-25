"""Comandos de administración (solo para IDs en ADMIN_IDS)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import wraps

from sqlalchemy import func, or_, select
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters

from bot.db.database import session_scope
from bot.db.models import Faq, Order, Plan, Service, StockItem, User, WalletTransaction
from bot.services.catalog_service import (
    add_plan,
    add_service,
    add_stock_lines,
    get_plan,
    get_service,
    list_active_plans,
    list_active_services,
    take_stock,
)
from bot.services.faq_service import add_faq, delete_faq, list_all_faqs
from bot.services.order_service import get_order, list_pending_orders
from bot.services.wallet_service import (
    add_balance as wallet_add_balance,
    list_top_balances,
    list_transactions,
    set_balance as wallet_set_balance,
)
from config import Settings

LOW_STOCK_THRESHOLD = 2

log = logging.getLogger(__name__)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def admin_only(func_):
    @wraps(func_)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if update.effective_user is None:
            return None
        settings = _settings(context)
        if update.effective_user.id not in settings.admin_ids:
            if update.message is not None:
                await update.message.reply_text("⛔ Solo los administradores pueden usar este comando.")
            elif update.callback_query is not None:
                await update.callback_query.answer("⛔ Solo administradores", show_alert=True)
            return None
        return await func_(update, context, *a, **kw)

    return wrapper


@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🛠 *Panel de administración*\n\n"
        "*Catálogo:*\n"
        "/addservice `<nombre>` `<emoji>` — añadir servicio\n"
        "/listservices — listar servicios\n"
        "/editservice `<id>` `<emoji>` `<nombre...>` — renombrar/cambiar emoji\n"
        "/delservice `<id>` — eliminar servicio (soft)\n"
        "/addplan `<service_id>` `<dias>` `<precio>` `<nombre...>` — añadir plan\n"
        "/listplans `<service_id>` — listar planes de un servicio\n"
        "/editprice `<plan_id>` `<precio>` — cambiar precio\n"
        "/editplan `<plan_id>` `<dias>` `<nombre...>` — cambiar duración/nombre\n"
        "/delplan `<plan_id>` — eliminar plan (soft)\n"
        "/enableplan `<plan_id>` / /disableplan `<plan_id>`\n\n"
        "*Stock:*\n"
        "/addstock `<plan_id>` — añadir credenciales (envía líneas, /done para terminar)\n\n"
        "*Pedidos:*\n"
        "/orders — pedidos en revisión\n"
        "/order `<id>` — detalle de un pedido\n"
        "/expiring — pedidos por vencer en 7 días\n"
        "/expired — pedidos vencidos pendientes de cortar\n"
        "/markcut `<id>` / /cutall — marcar como cortado\n\n"
        "*Saldo / billetera:*\n"
        "/addbalance `<tg_id>` `<monto>` — cargar saldo\n"
        "/setbalance `<tg_id>` `<monto>` — fijar saldo\n"
        "/balance `<tg_id>` — ver saldo de un cliente\n"
        "/topbalances — ranking de saldos\n"
        "/wallethistory `<tg_id>` — movimientos del cliente\n\n"
        "*Clientes / soporte:*\n"
        "/searchuser `<id|@user>` — buscar cliente\n"
        "/orderhistory `<user_id>` — todos los pedidos del cliente\n"
        "/reply `<telegram_id>` `<mensaje...>` — responder a un cliente\n\n"
        "*FAQ / soporte automático:*\n"
        "/addfaq `<pregunta> | <respuesta> | <palabras,clave>` — crear respuesta automática\n"
        "/listfaq — listar FAQs\n"
        "/delfaq `<id>` — eliminar FAQ\n\n"
        "*General:*\n"
        "/stats — estadísticas\n"
        "/broadcast `<mensaje>` — enviar a todos los usuarios"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------- catálogo ----------

@admin_only
async def cmd_add_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Uso: /addservice `<nombre>` `<emoji>`\nEjemplo: `/addservice Netflix 🎬`",
            parse_mode="Markdown",
        )
        return
    name = args[0]
    emoji = args[1] if len(args) > 1 else "🎬"
    description = " ".join(args[2:]) if len(args) > 2 else None
    with session_scope() as session:
        svc = add_service(session, name=name, emoji=emoji, description=description)
        msg = f"✅ Servicio creado: {svc.emoji} {svc.name} (id={svc.id})"
    await update.message.reply_text(msg)


@admin_only
async def cmd_list_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        services = list_active_services(session)
        if not services:
            await update.message.reply_text("No hay servicios.")
            return
        lines = ["*Servicios activos:*"]
        for s in services:
            lines.append(f"`{s.id}` — {s.emoji} {s.name}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 4:
        await update.message.reply_text(
            "Uso: /addplan `<service_id>` `<dias>` `<precio>` `<nombre...>`\n"
            "Ejemplo: `/addplan 1 30 4.50 1 Mes Perfil`",
            parse_mode="Markdown",
        )
        return
    try:
        service_id = int(args[0])
        days = int(args[1])
        price = float(args[2])
    except ValueError:
        await update.message.reply_text("service_id, días y precio deben ser números.")
        return
    name = " ".join(args[3:])
    with session_scope() as session:
        if get_service(session, service_id) is None:
            await update.message.reply_text("No existe ese service_id.")
            return
        plan = add_plan(
            session,
            service_id=service_id,
            name=name,
            duration_days=days,
            price=price,
            description=None,
        )
        await update.message.reply_text(
            f"✅ Plan creado: id={plan.id}, {name}, {days}d, {price:.2f}"
        )


@admin_only
async def cmd_list_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /listplans `<service_id>`", parse_mode="Markdown")
        return
    try:
        service_id = int(args[0])
    except ValueError:
        await update.message.reply_text("service_id debe ser un número.")
        return
    settings = _settings(context)
    with session_scope() as session:
        plans = list_active_plans(session, service_id)
        if not plans:
            await update.message.reply_text("No hay planes activos para ese servicio.")
            return
        lines = [f"*Planes del servicio {service_id}:*"]
        for p in plans:
            stock = session.scalar(
                select(func.count(StockItem.id)).where(
                    StockItem.plan_id == p.id, StockItem.is_sold.is_(False)
                )
            )
            lines.append(
                f"`{p.id}` — {p.name} — {p.duration_days}d — "
                f"{p.price:.2f} {settings.currency} — stock: {stock}"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_toggle_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /enableplan `<plan_id>` o /disableplan `<plan_id>`", parse_mode="Markdown")
        return
    try:
        plan_id = int(args[0])
    except ValueError:
        return
    enable = update.message.text.lower().startswith("/enableplan")
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await update.message.reply_text("Plan no encontrado.")
            return
        plan.is_active = enable
        await update.message.reply_text(
            f"Plan {plan_id} {'activado' if enable else 'desactivado'}."
        )


# ---------- edición / eliminación ----------

@admin_only
async def cmd_edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /editprice `<plan_id>` `<nuevo_precio>`\nEjemplo: `/editprice 4 18.50`",
            parse_mode="Markdown",
        )
        return
    try:
        plan_id = int(args[0])
        new_price = float(args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("plan_id y precio deben ser números.")
        return
    settings = _settings(context)
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await update.message.reply_text("Plan no encontrado.")
            return
        old = plan.price
        plan.price = new_price
        await update.message.reply_text(
            f"💰 Precio del plan {plan_id} ({plan.name}) actualizado: "
            f"{old:.2f} → *{new_price:.2f} {settings.currency}*",
            parse_mode="Markdown",
        )


@admin_only
async def cmd_edit_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Uso: /editplan `<plan_id>` `<dias>` `<nombre...>`\n"
            "Ejemplo: `/editplan 4 60 2 Meses Perfil`",
            parse_mode="Markdown",
        )
        return
    try:
        plan_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("plan_id y días deben ser números.")
        return
    name = " ".join(args[2:])
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await update.message.reply_text("Plan no encontrado.")
            return
        plan.duration_days = days
        plan.name = name
        await update.message.reply_text(
            f"✏️ Plan {plan_id} actualizado: {name} ({days}d)."
        )


@admin_only
async def cmd_edit_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Uso: /editservice `<id>` `<emoji>` `<nuevo_nombre...>`\n"
            "Ejemplo: `/editservice 1 🎬 Netflix Premium`",
            parse_mode="Markdown",
        )
        return
    try:
        service_id = int(args[0])
    except ValueError:
        await update.message.reply_text("service_id debe ser número.")
        return
    emoji = args[1]
    name = " ".join(args[2:])
    with session_scope() as session:
        svc = get_service(session, service_id)
        if svc is None:
            await update.message.reply_text("Servicio no encontrado.")
            return
        svc.emoji = emoji
        svc.name = name
        await update.message.reply_text(
            f"✏️ Servicio {service_id} actualizado: {emoji} {name}"
        )


@admin_only
async def cmd_del_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /delplan `<plan_id>`", parse_mode="Markdown")
        return
    try:
        plan_id = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await update.message.reply_text("Plan no encontrado.")
            return
        plan.is_active = False
        await update.message.reply_text(
            f"🗑 Plan {plan_id} eliminado (desactivado, se mantiene en historial)."
        )


@admin_only
async def cmd_del_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /delservice `<service_id>`", parse_mode="Markdown")
        return
    try:
        service_id = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        svc = get_service(session, service_id)
        if svc is None:
            await update.message.reply_text("Servicio no encontrado.")
            return
        svc.is_active = False
        # También desactivamos los planes del servicio.
        for plan in svc.plans:
            plan.is_active = False
        await update.message.reply_text(
            f"🗑 Servicio {service_id} eliminado (desactivado, junto a sus planes)."
        )


# ---------- stock (conversation) ----------

ASK_STOCK_LINES = 1


@admin_only
async def cmd_add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Uso: /addstock `<plan_id>`\n\n"
            "Después puedes:\n"
            "• Pegar las credenciales en el chat (1 por línea o 1 por mensaje), o\n"
            "• Subir un archivo *.txt* con 1 credencial por línea (más rápido para lotes).\n\n"
            "Cuando termines envía /done. Para abortar, /cancel.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    try:
        plan_id = int(args[0])
    except ValueError:
        await update.message.reply_text("plan_id debe ser un número.")
        return ConversationHandler.END
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None:
            await update.message.reply_text("Plan no encontrado.")
            return ConversationHandler.END
    context.user_data["stock_plan_id"] = plan_id
    context.user_data["stock_lines"] = []
    await update.message.reply_text(
        f"📥 Modo añadir stock al plan {plan_id} activado.\n\n"
        "Pega credenciales (1 por línea) *o* sube un archivo .txt con 1 por línea.\n"
        "Cuando termines envía /done. Para abortar, /cancel.",
        parse_mode="Markdown",
    )
    return ASK_STOCK_LINES


async def stock_collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if msg is None:
        return ASK_STOCK_LINES
    raw_text = ""
    if msg.document is not None:
        try:
            file = await msg.document.get_file()
            data = await file.download_as_bytearray()
            raw_text = data.decode("utf-8", errors="ignore")
        except Exception:
            log.exception("No pude leer el documento de stock")
            await msg.reply_text("No pude leer ese archivo. Envíalo como .txt.")
            return ASK_STOCK_LINES
    else:
        raw_text = (msg.text or "").strip()
    if not raw_text:
        return ASK_STOCK_LINES
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    context.user_data.setdefault("stock_lines", []).extend(lines)
    await msg.reply_text(
        f"➕ {len(lines)} líneas registradas. Total acumulado: "
        f"{len(context.user_data['stock_lines'])}. Envía /done para guardar."
    )
    return ASK_STOCK_LINES


async def stock_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plan_id = context.user_data.pop("stock_plan_id", None)
    lines = context.user_data.pop("stock_lines", [])
    if not plan_id:
        await update.message.reply_text("No estabas en modo añadir stock.")
        return ConversationHandler.END
    if not lines:
        await update.message.reply_text("No había nada que guardar.")
        return ConversationHandler.END
    with session_scope() as session:
        added = add_stock_lines(session, plan_id, lines)
    await update.message.reply_text(f"✅ Guardadas {added} credenciales en el plan {plan_id}.")
    await _notify_waitlist(context, plan_id)
    return ConversationHandler.END


async def _notify_waitlist(
    context: ContextTypes.DEFAULT_TYPE, plan_id: int
) -> None:
    """Avisa a quienes estaban en lista de espera de este plan."""
    from datetime import datetime as _dt

    from bot.services.waitlist_service import pending_for_plan

    targets: list[tuple[int, str]] = []
    with session_scope() as session:
        plan = get_plan(session, plan_id)
        plan_label = (
            f"{plan.service.emoji} {plan.service.name} — {plan.name}" if plan else f"Plan #{plan_id}"
        )
        entries = pending_for_plan(session, plan_id)
        for entry in entries:
            user = session.get(User, entry.user_id)
            if user is None or user.is_blocked:
                entry.notified_at = _dt.utcnow()
                continue
            targets.append((user.telegram_id, plan_label))
            entry.notified_at = _dt.utcnow()
    for tg_id, label in targets:
        try:
            await context.bot.send_message(
                tg_id,
                f"🔔 ¡Buenas noticias! Ya tenemos stock disponible de *{label}*.\n"
                "Entra a /catalogo para comprarla antes de que se acabe.",
                parse_mode="Markdown",
            )
        except Exception:
            log.exception("No se pudo notificar a %s en lista de espera", tg_id)


async def stock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("stock_plan_id", None)
    context.user_data.pop("stock_lines", None)
    await update.message.reply_text("Cancelado. No se guardó nada.")
    return ConversationHandler.END


# ---------- pedidos ----------

@admin_only
async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    with session_scope() as session:
        pending = list_pending_orders(session)
        if not pending:
            await update.message.reply_text("📭 No hay pedidos en revisión.")
            return
        lines = ["🔍 *Pedidos en revisión:*", ""]
        for o in pending:
            uname = o.user.username or "—"
            lines.append(
                f"#{o.id} — {o.plan.service.name} {o.plan.name} — "
                f"{o.price:.2f} {settings.currency} — @{uname} (tg={o.user.telegram_id})"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /order `<id>`", parse_mode="Markdown")
        return
    try:
        order_id = int(args[0])
    except ValueError:
        return
    settings = _settings(context)
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await update.message.reply_text("Pedido no encontrado.")
            return
        text = (
            f"*Pedido #{order.id}*\n"
            f"Cliente: {order.user.full_name or '—'} (@{order.user.username or '—'})\n"
            f"Telegram ID: `{order.user.telegram_id}`\n"
            f"Producto: {order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}\n"
            f"Total: {order.price:.2f} {settings.currency}\n"
            f"Estado: {order.status}\n"
            f"Creado: {order.created_at:%Y-%m-%d %H:%M}\n"
        )
        if order.delivered_credentials:
            text += f"\nCredenciales entregadas:\n`{order.delivered_credentials}`"
    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def cb_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los callbacks `adm:approve:<id>` y `adm:reject:<id>`."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    action = parts[1]
    try:
        order_id = int(parts[2])
    except ValueError:
        await query.answer()
        return

    settings = _settings(context)
    delivered_text: str | None = None
    notify_user_id: int | None = None
    notify_text: str | None = None
    edit_text: str

    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await query.answer("Pedido no encontrado", show_alert=True)
            return
        if order.status not in (Order.STATUS_AWAITING_REVIEW, Order.STATUS_PENDING_PAYMENT):
            await query.answer(
                f"Pedido ya procesado (estado: {order.status})", show_alert=True
            )
            return

        notify_user_id = order.user.telegram_id
        low_stock_info: tuple[str, int] | None = None

        commission_for_referrer: tuple[int, float] | None = None
        promoted_to_level: int | None = None
        if action == "approve":
            stock_item = take_stock(session, order.plan_id)
            if stock_item is None:
                await query.answer("Sin stock disponible para entregar", show_alert=True)
                return
            now = datetime.utcnow()
            order.status = Order.STATUS_DELIVERED
            order.delivered_credentials = stock_item.credentials
            order.delivered_at = now
            order.expires_at = now + timedelta(days=order.plan.duration_days)
            order.review_requested_at = now
            delivered_text = stock_item.credentials
            from bot.services.referral_service import maybe_pay_commission
            from bot.services.vip_service import maybe_promote_vip

            commission = maybe_pay_commission(session, order)
            if commission > 0 and order.user.referred_by_id is not None:
                ref_user = session.get(User, order.user.referred_by_id)
                if ref_user is not None:
                    commission_for_referrer = (ref_user.telegram_id, commission)
            promoted_to_level = maybe_promote_vip(
                session,
                order.user,
                settings.vip_threshold_1,
                settings.vip_threshold_2,
            )
            edit_text = f"✅ Pedido #{order_id} aprobado y entregado."
            notify_text = (
                f"🎉 *¡Tu pedido #{order_id} ha sido entregado!*\n\n"
                f"Producto: {order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}\n"
                f"Duración: {order.plan.duration_days} días "
                f"(vence el {order.expires_at:%Y-%m-%d})\n\n"
                f"*Credenciales:*\n```\n{stock_item.credentials}\n```\n\n"
                "⚠️ No compartas estos datos. Si tienes problemas usa /garantia "
                f"{order_id}."
            )
            # Comprobar stock restante y avisar si es bajo.
            remaining = session.scalar(
                select(func.count(StockItem.id)).where(
                    StockItem.plan_id == order.plan_id, StockItem.is_sold.is_(False)
                )
            )
            if remaining <= LOW_STOCK_THRESHOLD:
                low_stock_info = (
                    f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}",
                    int(remaining),
                )
        elif action == "reject":
            order.status = Order.STATUS_REJECTED
            order.admin_note = "Rechazado por admin."
            edit_text = f"🚫 Pedido #{order_id} rechazado."
            notify_text = (
                f"❌ Tu pedido #{order_id} fue rechazado por un administrador.\n"
                "Si crees que es un error, contáctanos por /soporte."
            )
        else:
            await query.answer("Acción desconocida", show_alert=True)
            return

    await query.answer("Listo")
    try:
        await query.edit_message_text(edit_text)
    except Exception:
        await query.message.reply_text(edit_text)

    if notify_user_id and notify_text:
        try:
            await context.bot.send_message(
                notify_user_id, notify_text, parse_mode="Markdown"
            )
        except Exception:
            log.exception("No se pudo notificar al usuario %s", notify_user_id)

    if low_stock_info is not None:
        plan_label, remaining = low_stock_info
        alert = (
            f"⚠️ *Stock bajo*: {plan_label} — quedan *{remaining}* "
            f"credencial{'es' if remaining != 1 else ''}.\n"
            "Usa /addstock para reponer."
        )
        for admin_id in _settings(context).admin_ids:
            try:
                await context.bot.send_message(admin_id, alert, parse_mode="Markdown")
            except Exception:
                log.exception("No se pudo enviar aviso de stock bajo a %s", admin_id)

    # Aviso al referidor + solicitud de reseña.
    if action == "approve":
        if commission_for_referrer is not None:
            ref_tg_id, commission = commission_for_referrer
            try:
                await context.bot.send_message(
                    ref_tg_id,
                    f"🎁 ¡Tu referido hizo su primera compra! Acabas de ganar "
                    f"*+{commission:.2f} {settings.currency}* en saldo.\n"
                    "Mira tu /saldo para usarlo en tu próxima compra.",
                    parse_mode="Markdown",
                )
            except Exception:
                log.exception("No se pudo avisar al referidor")
        if notify_user_id:
            try:
                from bot.keyboards import review_keyboard
                await context.bot.send_message(
                    notify_user_id,
                    "🌟 ¿Cómo te fue con esta compra? Tu opinión nos ayuda.",
                    reply_markup=review_keyboard(order_id),
                )
            except Exception:
                log.exception("No se pudo pedir reseña")
        if promoted_to_level is not None and notify_user_id:
            try:
                from bot.handlers.orders import _notify_vip_promotion

                await _notify_vip_promotion(
                    context, notify_user_id, promoted_to_level
                )
            except Exception:
                log.exception("No se pudo notificar promoción VIP")


# ---------- stats / broadcast ----------

@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.db.models import User as UserModel  # import local para evitar ciclos
    settings = _settings(context)
    with session_scope() as session:
        total_users = session.scalar(select(func.count(UserModel.id)))
        total_services = session.scalar(select(func.count(Service.id)))
        total_plans = session.scalar(select(func.count(Plan.id)))
        total_stock = session.scalar(
            select(func.count(StockItem.id)).where(StockItem.is_sold.is_(False))
        )
        sold_orders = session.scalar(
            select(func.count(Order.id)).where(Order.status == Order.STATUS_DELIVERED)
        )
        revenue = session.scalar(
            select(func.coalesce(func.sum(Order.price), 0.0)).where(
                Order.status == Order.STATUS_DELIVERED
            )
        )
        pending = session.scalar(
            select(func.count(Order.id)).where(Order.status == Order.STATUS_AWAITING_REVIEW)
        )
    text = (
        "📊 *Estadísticas*\n\n"
        f"👥 Usuarios: {total_users}\n"
        f"🛍 Servicios: {total_services}\n"
        f"🧾 Planes: {total_plans}\n"
        f"📦 Stock disponible: {total_stock}\n"
        f"⏳ Pedidos en revisión: {pending}\n"
        f"✅ Pedidos entregados: {sold_orders}\n"
        f"💵 Ingresos (entregados): {revenue:.2f} {settings.currency}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /broadcast `<mensaje>`", parse_mode="Markdown")
        return
    text = update.message.text.split(" ", 1)[1]
    from bot.db.models import User as UserModel
    sent = 0
    failed = 0
    with session_scope() as session:
        ids = [tg for (tg,) in session.execute(select(UserModel.telegram_id))]
    for tg in ids:
        try:
            await context.bot.send_message(tg, text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📣 Broadcast enviado: {sent} ok, {failed} fallidos.")


# ---------- FAQ ----------

@admin_only
async def cmd_add_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = update.message.text.split(" ", 1)
    if len(raw) < 2 or "|" not in raw[1]:
        await update.message.reply_text(
            "Uso: /addfaq `<pregunta> | <respuesta> | <palabras,clave>`\n"
            "Ejemplo: `/addfaq ¿No me funciona la cuenta? | Verifica que escribas bien la clave. "
            "Si sigue fallando avísanos. | no funciona,no entra,error,clave,bloqueada`",
            parse_mode="Markdown",
        )
        return
    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) < 2:
        await update.message.reply_text("Faltan partes. Usa el separador | entre pregunta, respuesta y palabras clave.")
        return
    question = parts[0]
    answer = parts[1]
    keywords = parts[2] if len(parts) >= 3 else ""
    with session_scope() as session:
        faq = add_faq(session, question, answer, keywords or None)
        await update.message.reply_text(f"✅ FAQ #{faq.id} guardada.")


@admin_only
async def cmd_list_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        faqs = list_all_faqs(session)
        if not faqs:
            await update.message.reply_text("Aún no hay FAQs.")
            return
        lines = ["*FAQs configurados:*", ""]
        for f in faqs:
            status = "🟢" if f.is_active else "🔴"
            lines.append(f"{status} `#{f.id}` — *{f.question}*")
            lines.append(f"    └ kw: `{f.keywords or '—'}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_del_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /delfaq `<id>`", parse_mode="Markdown")
        return
    try:
        faq_id = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        ok = delete_faq(session, faq_id)
    await update.message.reply_text(
        f"🗑 FAQ {faq_id} eliminada." if ok else f"FAQ {faq_id} no encontrada."
    )


# ---------- soporte / clientes ----------

@admin_only
async def cmd_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Uso: /searchuser `<id|@username|nombre>`", parse_mode="Markdown"
        )
        return
    needle = args[0].lstrip("@").lower()
    with session_scope() as session:
        if needle.isdigit():
            stmt = select(User).where(User.telegram_id == int(needle))
        else:
            stmt = select(User).where(
                or_(
                    func.lower(User.username) == needle,
                    func.lower(User.full_name).like(f"%{needle}%"),
                )
            )
        users = list(session.scalars(stmt).all())[:10]
        if not users:
            await update.message.reply_text("No encontré usuarios con ese criterio.")
            return
        lines = ["*Resultados:*", ""]
        for u in users:
            lines.append(
                f"`#{u.id}` — TG `{u.telegram_id}` — @{u.username or '—'} — {u.full_name or '—'}"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_order_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /orderhistory `<user_id>` (id interno o telegram_id)", parse_mode="Markdown")
        return
    try:
        ident = int(args[0])
    except ValueError:
        return
    settings = _settings(context)
    with session_scope() as session:
        # Permite buscar por telegram_id o por id interno.
        user = session.scalar(select(User).where(User.telegram_id == ident))
        if user is None:
            user = session.get(User, ident)
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        from bot.services.order_service import list_user_orders
        orders = list_user_orders(session, user.id, limit=50)
        if not orders:
            await update.message.reply_text(f"El usuario {user.id} no tiene pedidos.")
            return
        lines = [f"*Historial de @{user.username or user.full_name or user.id}:*", ""]
        for o in orders:
            lines.append(
                f"#{o.id} — {o.plan.service.emoji} {o.plan.service.name} {o.plan.name} — "
                f"{o.price:.2f} {settings.currency} — {o.status}"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_expiring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    soon = datetime.utcnow() + timedelta(days=7)
    with session_scope() as session:
        stmt = (
            select(Order)
            .where(
                Order.status == Order.STATUS_DELIVERED,
                Order.expires_at.isnot(None),
                Order.expires_at <= soon,
            )
            .order_by(Order.expires_at)
            .limit(50)
        )
        orders = list(session.scalars(stmt))
        if not orders:
            await update.message.reply_text("No hay pedidos por vencer en los próximos 7 días.")
            return
        lines = ["⏰ *Pedidos por vencer en 7 días:*", ""]
        for o in orders:
            uname = o.user.username or o.user.full_name or o.user.telegram_id
            lines.append(
                f"#{o.id} — @{uname} — {o.plan.service.name} {o.plan.name} — "
                f"vence {o.expires_at:%Y-%m-%d}"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /reply `<telegram_id>` `<mensaje...>`\nEjemplo: `/reply 987654321 Hola, ya revisé tu pedido`",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("telegram_id debe ser un número.")
        return
    text = update.message.text.split(" ", 2)[2]
    try:
        await context.bot.send_message(target_id, f"💬 *Soporte:*\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ Mensaje enviado.")
    except Exception as e:
        await update.message.reply_text(f"❌ No se pudo enviar: {e}")


# ---------- saldo / wallet ----------

def _parse_amount(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


@admin_only
async def cmd_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /addbalance `<telegram_id>` `<monto>` `[nota]`\n"
            "Ejemplo: `/addbalance 555666777 50 Recarga Yape`",
            parse_mode="Markdown",
        )
        return
    try:
        tg_id = int(args[0])
    except ValueError:
        await update.message.reply_text("telegram_id debe ser número.")
        return
    amount = _parse_amount(args[1])
    if amount is None:
        await update.message.reply_text("Monto inválido.")
        return
    note = " ".join(args[2:]) if len(args) > 2 else None
    settings = _settings(context)
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            await update.message.reply_text(
                "Ese usuario aún no ha hablado con el bot. Pídele que envíe /start primero."
            )
            return
        new_bal = wallet_add_balance(session, user, amount, note=note)
        username = user.username or user.full_name or str(user.telegram_id)

    await update.message.reply_text(
        f"💰 Saldo actualizado para @{username}: "
        f"+{amount:.2f} {settings.currency} (nuevo total: *{new_bal:.2f}*)",
        parse_mode="Markdown",
    )
    # Notificar al cliente.
    try:
        await context.bot.send_message(
            tg_id,
            f"🟢 Tu saldo fue *recargado*: +{amount:.2f} {settings.currency}\n"
            f"Saldo actual: *{new_bal:.2f} {settings.currency}*\n\n"
            "Ya puedes comprar al instante usando 💰 Pagar con saldo en el catálogo.",
            parse_mode="Markdown",
        )
    except Exception:
        log.exception("No se pudo notificar al usuario %s", tg_id)


@admin_only
async def cmd_set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /setbalance `<telegram_id>` `<monto>`",
            parse_mode="Markdown",
        )
        return
    try:
        tg_id = int(args[0])
    except ValueError:
        return
    amount = _parse_amount(args[1])
    if amount is None:
        await update.message.reply_text("Monto inválido.")
        return
    settings = _settings(context)
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        wallet_set_balance(session, user, amount, note="Ajuste manual")
    await update.message.reply_text(
        f"✏️ Saldo fijado a *{amount:.2f} {settings.currency}*.",
        parse_mode="Markdown",
    )


@admin_only
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /balance `<telegram_id>`", parse_mode="Markdown")
        return
    try:
        tg_id = int(args[0])
    except ValueError:
        return
    settings = _settings(context)
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        username = user.username or user.full_name or str(user.telegram_id)
        bal = float(user.balance or 0.0)
    await update.message.reply_text(
        f"💰 @{username} — Saldo: *{bal:.2f} {settings.currency}*",
        parse_mode="Markdown",
    )


@admin_only
async def cmd_top_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    with session_scope() as session:
        users = list_top_balances(session, limit=15)
        if not users:
            await update.message.reply_text("No hay clientes con saldo.")
            return
        lines = ["💰 *Top saldos:*", ""]
        for u in users:
            uname = u.username or u.full_name or u.telegram_id
            lines.append(f"@{uname} (TG `{u.telegram_id}`) — {u.balance:.2f} {settings.currency}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_wallet_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Uso: /wallethistory `<telegram_id>`", parse_mode="Markdown"
        )
        return
    try:
        tg_id = int(args[0])
    except ValueError:
        return
    settings = _settings(context)
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        txs = list_transactions(session, user.id, limit=30)
        if not txs:
            await update.message.reply_text("Sin movimientos.")
            return
        lines = [f"💼 *Historial @{user.username or user.full_name or tg_id}:*", ""]
        for t in txs:
            sign = "+" if t.amount >= 0 else "−"
            lines.append(
                f"`{t.created_at:%Y-%m-%d %H:%M}` {t.kind}: "
                f"{sign}{abs(t.amount):.2f} {settings.currency}"
                f"{' — ' + t.note if t.note else ''}"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------- vencimiento / corte ----------

@admin_only
async def cmd_expired(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista pedidos vencidos que aún no han sido marcados como cortados."""
    now = datetime.utcnow()
    with session_scope() as session:
        stmt = (
            select(Order)
            .where(
                Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]),
                Order.expires_at.isnot(None),
                Order.expires_at <= now,
                Order.cut_at.is_(None),
            )
            .order_by(Order.expires_at)
            .limit(100)
        )
        orders = list(session.scalars(stmt))
        if not orders:
            await update.message.reply_text(
                "✅ No hay pedidos vencidos pendientes de cortar."
            )
            return
        lines = [
            f"⌛ *Vencidos pendientes de cortar* ({len(orders)}):",
            "",
            "Para cada uno, da de baja el acceso en la plataforma "
            "y luego marca el pedido con `/markcut <id>` (o todos con `/cutall`).",
            "",
        ]
        for o in orders:
            uname = o.user.username or o.user.full_name or o.user.telegram_id
            cred = (o.delivered_credentials or "").split("\n")[0][:80]
            lines.append(
                f"#{o.id} — @{uname} (TG `{o.user.telegram_id}`)\n"
                f"  {o.plan.service.emoji} {o.plan.service.name} — {o.plan.name}\n"
                f"  Vencido: {o.expires_at:%Y-%m-%d}\n"
                f"  Credencial: `{cred}`\n"
            )
    # Telegram limita 4096 chars por mensaje; cortamos por las dudas.
    text = "\n".join(lines)
    for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


@admin_only
async def cmd_mark_cut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Uso: /markcut `<order_id>`", parse_mode="Markdown")
        return
    try:
        order_id = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await update.message.reply_text("Pedido no encontrado.")
            return
        order.cut_at = datetime.utcnow()
        if order.status != Order.STATUS_EXPIRED:
            order.status = Order.STATUS_EXPIRED
    await update.message.reply_text(f"✂️ Pedido #{order_id} marcado como cortado.")


@admin_only
async def cmd_cut_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca como cortados todos los pedidos vencidos pendientes."""
    now = datetime.utcnow()
    count = 0
    with session_scope() as session:
        stmt = select(Order).where(
            Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]),
            Order.expires_at.isnot(None),
            Order.expires_at <= now,
            Order.cut_at.is_(None),
        )
        for o in session.scalars(stmt):
            o.cut_at = now
            o.status = Order.STATUS_EXPIRED
            count += 1
    await update.message.reply_text(
        f"✂️ {count} pedido{'s' if count != 1 else ''} marcado{'s' if count != 1 else ''} como cortado{'s' if count != 1 else ''}."
    )


# ---------- cupones ----------

@admin_only
async def cmd_add_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /addcoupon `<CÓDIGO>` `<descuento>` `[max_usos]` `[días_validez]`\n\n"
            "Ejemplos:\n"
            "• `/addcoupon NETFLIX20 20%` — 20% off ilimitado\n"
            "• `/addcoupon WELCOME 5` — 5 soles off\n"
            "• `/addcoupon BLACK50 50% 100 7` — 50%, máximo 100 usos, válido 7 días",
            parse_mode="Markdown",
        )
        return
    from bot.services.coupon_service import add_coupon, get_coupon_by_code
    code = args[0].upper().strip()
    raw = args[1]
    is_pct = raw.endswith("%")
    try:
        amount = float(raw.rstrip("%").replace(",", "."))
    except ValueError:
        await update.message.reply_text("Descuento inválido.")
        return
    max_uses = 0
    days_valid = 0
    try:
        if len(args) >= 3:
            max_uses = max(0, int(args[2]))
        if len(args) >= 4:
            days_valid = max(0, int(args[3]))
    except ValueError:
        await update.message.reply_text("max_usos / días inválidos.")
        return
    expires = (datetime.utcnow() + timedelta(days=days_valid)) if days_valid else None
    with session_scope() as session:
        if get_coupon_by_code(session, code) is not None:
            await update.message.reply_text("Ese código ya existe.")
            return
        coupon = add_coupon(
            session,
            code,
            discount_percent=(amount if is_pct else 0.0),
            discount_amount=(0.0 if is_pct else amount),
            max_uses=max_uses,
            expires_at=expires,
        )
        cid = coupon.id
    desc = f"{amount:.0f}%" if is_pct else f"{amount:.2f}"
    extras = []
    if max_uses:
        extras.append(f"máx {max_uses} usos")
    if expires:
        extras.append(f"vence {expires:%Y-%m-%d}")
    suffix = f" ({', '.join(extras)})" if extras else ""
    await update.message.reply_text(
        f"🎟 Cupón creado: `{code}` — {desc} off{suffix} (id={cid})",
        parse_mode="Markdown",
    )


@admin_only
async def cmd_list_coupons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.services.coupon_service import list_coupons
    with session_scope() as session:
        coupons = list_coupons(session)
        if not coupons:
            await update.message.reply_text("Sin cupones.")
            return
        lines = ["🎟 *Cupones:*", ""]
        for c in coupons:
            d = f"{c.discount_percent:.0f}%" if c.discount_percent else f"{c.discount_amount:.2f}"
            uses = f"{c.uses}/{c.max_uses}" if c.max_uses else f"{c.uses}/∞"
            exp = c.expires_at.strftime("%Y-%m-%d") if c.expires_at else "sin caducidad"
            state = "🟢" if c.is_active else "🔴"
            lines.append(f"{state} `{c.code}` — {d} — usos {uses} — {exp} (id={c.id})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_del_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /delcoupon `<id>`", parse_mode="Markdown")
        return
    try:
        cid = int(args[0])
    except ValueError:
        return
    from bot.services.coupon_service import delete_coupon
    with session_scope() as session:
        ok = delete_coupon(session, cid)
    await update.message.reply_text("🗑 Cupón desactivado." if ok else "No encontrado.")


# ---------- refund / replace ----------

@admin_only
async def cmd_refund(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /refund `<order_id>`\n"
            "Devuelve el monto al saldo del cliente y marca el pedido como reembolsado.",
            parse_mode="Markdown",
        )
        return
    try:
        order_id = int(args[0])
    except ValueError:
        return
    settings = _settings(context)
    notify_user: tuple[int, float, str] | None = None
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await update.message.reply_text("Pedido no encontrado.")
            return
        if order.status == Order.STATUS_REFUNDED:
            await update.message.reply_text("Este pedido ya fue reembolsado.")
            return
        amount = max(0.0, order.price - (order.discount_amount or 0.0))
        wallet_add_balance(
            session,
            order.user,
            amount,
            kind=WalletTransaction.KIND_REFUND,
            note=f"Reembolso pedido #{order.id}",
            related_order_id=order.id,
        )
        order.status = Order.STATUS_REFUNDED
        order.admin_note = (order.admin_note or "") + f"\nReembolsado {datetime.utcnow():%Y-%m-%d %H:%M}"
        notify_user = (
            order.user.telegram_id,
            amount,
            f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}",
        )
    await update.message.reply_text(
        f"↩️ Pedido #{order_id} reembolsado: +{notify_user[1]:.2f} "
        f"{settings.currency} al saldo del cliente."
    )
    try:
        await context.bot.send_message(
            notify_user[0],
            f"↩️ Tu pedido *#{order_id}* ({notify_user[2]}) fue reembolsado: "
            f"+{notify_user[1]:.2f} {settings.currency} acreditados a tu /saldo.",
            parse_mode="Markdown",
        )
    except Exception:
        log.exception("No se pudo notificar reembolso")


@admin_only
async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entrega una nueva credencial del stock al mismo cliente sin cobrarle."""
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /replace `<order_id>` — entrega cuenta nueva del stock como garantía.",
            parse_mode="Markdown",
        )
        return
    try:
        order_id = int(args[0])
    except ValueError:
        return
    notify: tuple[int, str, str] | None = None
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await update.message.reply_text("Pedido no encontrado.")
            return
        new_item = take_stock(session, order.plan_id)
        if new_item is None:
            await update.message.reply_text("⛔ Sin stock disponible para reponer.")
            return
        order.delivered_credentials = new_item.credentials
        order.delivered_at = datetime.utcnow()
        # Mantenemos la fecha de vencimiento original (no se extiende).
        order.admin_note = (order.admin_note or "") + (
            f"\nReposición {datetime.utcnow():%Y-%m-%d %H:%M}"
        )
        plan_label = f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}"
        notify = (order.user.telegram_id, plan_label, new_item.credentials)
    await update.message.reply_text(
        f"♻️ Pedido #{order_id} repuesto con cuenta nueva."
    )
    if notify:
        try:
            await context.bot.send_message(
                notify[0],
                f"♻️ *Reposición de garantía — Pedido #{order_id}*\n\n"
                f"Producto: {notify[1]}\n\n"
                f"*Nuevas credenciales:*\n```\n{notify[2]}\n```\n\n"
                "⚠️ La fecha de vencimiento no cambia.",
                parse_mode="Markdown",
            )
        except Exception:
            log.exception("No se pudo notificar reposición")


# ---------- bloqueo / nota / vip ----------

@admin_only
async def cmd_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /blockuser `<tg_id>`", parse_mode="Markdown")
        return
    try:
        tg = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        user.is_blocked = True
    await update.message.reply_text(f"⛔ Usuario {tg} bloqueado.")


@admin_only
async def cmd_unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /unblock `<tg_id>`", parse_mode="Markdown")
        return
    try:
        tg = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        user.is_blocked = False
    await update.message.reply_text(f"✅ Usuario {tg} desbloqueado.")


@admin_only
async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /note `<tg_id>` `<texto>` — guarda nota interna sobre el cliente.",
            parse_mode="Markdown",
        )
        return
    try:
        tg = int(args[0])
    except ValueError:
        return
    text = " ".join(args[1:]).strip()
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        user.internal_note = text
    await update.message.reply_text("📝 Nota guardada.")


@admin_only
async def cmd_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /vip `<tg_id>` `<nivel>` — nivel 0=normal, 1=plata (5%), 2=oro (10%).",
            parse_mode="Markdown",
        )
        return
    try:
        tg = int(args[0])
        level = int(args[1])
    except ValueError:
        return
    if level not in (0, 1, 2):
        await update.message.reply_text("Nivel inválido (0/1/2).")
        return
    with session_scope() as session:
        user = session.scalar(select(User).where(User.telegram_id == tg))
        if user is None:
            await update.message.reply_text("Usuario no encontrado.")
            return
        user.vip_level = level
    label = {0: "normal", 1: "PLATA (5% off)", 2: "ORO (10% off)"}[level]
    await update.message.reply_text(f"⭐ Nivel VIP de {tg}: {label}")
    try:
        await context.bot.send_message(
            tg, f"⭐ Tu nivel VIP fue actualizado a *{label}*.", parse_mode="Markdown"
        )
    except Exception:
        pass


# ---------- tickets / reseñas ----------

@admin_only
async def cmd_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.services.warranty_service import list_open
    with session_scope() as session:
        tickets = list_open(session)
        if not tickets:
            await update.message.reply_text("✅ No hay tickets abiertos.")
            return
        lines = [f"🚨 *Tickets abiertos ({len(tickets)})*:", ""]
        for t in tickets:
            uname = t.user.username if hasattr(t, "user") else None
            user = session.get(User, t.user_id)
            order = session.get(Order, t.order_id)
            uname = (user.username or user.full_name or user.telegram_id) if user else "?"
            plan_label = (
                f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}"
                if order else "?"
            )
            lines.append(
                f"#{t.id} (pedido #{t.order_id}) — @{uname}\n"
                f"  {plan_label}\n"
                f"  {t.message or '(sin descripción)'}\n"
                f"  Acciones: /replace {t.order_id} | /refund {t.order_id} | /resolveticket {t.id}\n"
            )
    text = "\n".join(lines)
    for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


@admin_only
async def cmd_resolve_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /resolveticket `<id>`", parse_mode="Markdown")
        return
    try:
        tid = int(args[0])
    except ValueError:
        return
    from bot.services.warranty_service import resolve
    with session_scope() as session:
        ok = resolve(session, tid, "Resuelto por admin.")
    await update.message.reply_text("✅ Ticket marcado como resuelto." if ok else "Ticket no encontrado.")


@admin_only
async def cmd_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.services.review_service import average_rating, list_recent_reviews
    with session_scope() as session:
        avg, cnt = average_rating(session)
        reviews = list_recent_reviews(session, limit=15)
        if not reviews:
            await update.message.reply_text("Sin reseñas todavía.")
            return
        lines = [f"⭐ *Promedio:* {avg:.2f} ({cnt} reseñas)", ""]
        for r in reviews:
            user = session.get(User, r.user_id)
            order = session.get(Order, r.order_id)
            uname = (user.username or user.full_name) if user else "?"
            label = (
                f"{order.plan.service.emoji} {order.plan.service.name}" if order else "?"
            )
            lines.append(
                f"{'⭐' * r.rating} — pedido #{r.order_id} ({label}) — @{uname}"
                + (f"\n  _{r.comment}_" if r.comment else "")
            )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------- stock admin extra ----------

@admin_only
async def cmd_stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /stocklist `<plan_id>`", parse_mode="Markdown")
        return
    try:
        plan_id = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        items = list(
            session.scalars(
                select(StockItem).where(StockItem.plan_id == plan_id).order_by(StockItem.id)
            )
        )
        if not items:
            await update.message.reply_text("Plan sin stock cargado.")
            return
        lines = [f"📦 *Stock del plan #{plan_id}:*", ""]
        for s_ in items:
            mark = "❌vendido" if s_.is_sold else "🟢disponible"
            head = (s_.credentials or "").split("\n")[0][:60]
            tag = f" [{s_.tag}]" if s_.tag else ""
            lines.append(f"#{s_.id} {mark}{tag} — `{head}`")
    text = "\n".join(lines)
    for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


@admin_only
async def cmd_del_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /delstock `<stock_id>`", parse_mode="Markdown")
        return
    try:
        sid = int(args[0])
    except ValueError:
        return
    with session_scope() as session:
        item = session.get(StockItem, sid)
        if item is None:
            await update.message.reply_text("Stock no encontrado.")
            return
        if item.is_sold:
            await update.message.reply_text("Esa credencial ya fue vendida; no se puede borrar.")
            return
        session.delete(item)
    await update.message.reply_text(f"🗑 Stock #{sid} eliminado.")


# ---------- marketing ----------

@admin_only
async def cmd_broadcast_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Uso: /broadcast_service `<service_id>` `<mensaje>` — "
            "envía el mensaje sólo a clientes que han comprado ese servicio.",
            parse_mode="Markdown",
        )
        return
    try:
        sid = int(args[0])
    except ValueError:
        return
    text = " ".join(args[1:]).strip()
    with session_scope() as session:
        service = session.get(Service, sid)
        if service is None:
            await update.message.reply_text("Servicio no encontrado.")
            return
        rows = session.execute(
            select(User.telegram_id)
            .join(Order, Order.user_id == User.id)
            .join(Plan, Plan.id == Order.plan_id)
            .where(
                Plan.service_id == sid,
                Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]),
                User.is_blocked.is_(False),
            )
            .distinct()
        ).all()
        targets = [r[0] for r in rows]
    sent, failed = 0, 0
    for tg in targets:
        try:
            await context.bot.send_message(tg, text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"📣 Broadcast a clientes de {service.emoji} {service.name}: "
        f"{sent} ok, {failed} fallidos."
    )


@admin_only
async def cmd_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/promo <texto>` — pone banner arriba del catálogo. `/promo off` lo quita."""
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /promo `<texto>` — banner que aparece arriba del catálogo.\n"
            "Usa `/promo off` para quitarlo.",
            parse_mode="Markdown",
        )
        return
    from bot.services.runtime_config_service import KEY_PROMO, delete, set_value
    text = " ".join(args).strip()
    with session_scope() as session:
        if text.lower() in ("off", "none", "quitar", "borrar", "-"):
            delete(session, KEY_PROMO)
            await update.message.reply_text("🗑 Promo quitada del catálogo.")
        else:
            set_value(session, KEY_PROMO, text)
            await update.message.reply_text(f"📣 Promo activa: {text}")


# ---------- reportes ----------

def _stats_period(period: str) -> tuple[datetime, str]:
    now = datetime.utcnow()
    if period == "hoy":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "semana":
        start = now - timedelta(days=7)
    elif period == "mes":
        start = now - timedelta(days=30)
    else:
        start = datetime(2000, 1, 1)
        period = "total"
    return start, period


@admin_only
async def cmd_stats_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/stats hoy|semana|mes` o sin args = total (delegar a cmd_stats)."""
    args = context.args or []
    if not args:
        await cmd_stats(update, context)
        return
    period = args[0].lower()
    start, period = _stats_period(period)
    settings = _settings(context)
    with session_scope() as session:
        delivered_q = select(Order).where(
            Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]),
            Order.delivered_at.isnot(None),
            Order.delivered_at >= start,
        )
        delivered = list(session.scalars(delivered_q))
        gross = sum(max(0.0, o.price - (o.discount_amount or 0.0)) for o in delivered)
        cnt = len(delivered)
    await update.message.reply_text(
        f"📊 *Stats — {period}*\n\n"
        f"Pedidos entregados: *{cnt}*\n"
        f"Ingresos: *{gross:.2f} {settings.currency}*",
        parse_mode="Markdown",
    )


@admin_only
async def cmd_top_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    with session_scope() as session:
        rows = session.execute(
            select(
                Service.id, Service.name, Service.emoji,
                func.count(Order.id).label("c"),
                func.coalesce(func.sum(Order.price), 0.0).label("rev"),
            )
            .join(Plan, Plan.service_id == Service.id)
            .join(Order, Order.plan_id == Plan.id)
            .where(Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]))
            .group_by(Service.id)
            .order_by(func.count(Order.id).desc())
            .limit(15)
        ).all()
    if not rows:
        await update.message.reply_text("Sin ventas todavía.")
        return
    lines = ["🏆 *Top servicios:*", ""]
    for _id, name, emoji, c, rev in rows:
        lines.append(f"{emoji} {name} — {c} ventas — {rev:.2f} {settings.currency}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_top_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    with session_scope() as session:
        rows = session.execute(
            select(
                User.id, User.telegram_id, User.username, User.full_name,
                func.count(Order.id).label("c"),
                func.coalesce(func.sum(Order.price), 0.0).label("rev"),
            )
            .join(Order, Order.user_id == User.id)
            .where(Order.status.in_([Order.STATUS_DELIVERED, Order.STATUS_EXPIRED]))
            .group_by(User.id)
            .order_by(func.coalesce(func.sum(Order.price), 0.0).desc())
            .limit(15)
        ).all()
    if not rows:
        await update.message.reply_text("Sin ventas todavía.")
        return
    lines = ["🏆 *Top clientes:*", ""]
    for _id, tg, uname, fn, c, rev in rows:
        label = uname or fn or str(tg)
        lines.append(f"@{label} (TG `{tg}`) — {c} pedidos — {rev:.2f} {settings.currency}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/export` — manda un CSV con todos los pedidos."""
    import csv
    import io
    settings = _settings(context)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "order_id", "user_tg_id", "username", "service", "plan",
        "status", "payment_method", "price", "discount", "final",
        "currency", "created_at", "delivered_at", "expires_at",
    ])
    with session_scope() as session:
        orders = list(session.scalars(select(Order).order_by(Order.id)))
        for o in orders:
            final = max(0.0, o.price - (o.discount_amount or 0.0))
            w.writerow([
                o.id,
                o.user.telegram_id,
                o.user.username or o.user.full_name or "",
                o.plan.service.name,
                o.plan.name,
                o.status,
                o.payment_method,
                f"{o.price:.2f}",
                f"{(o.discount_amount or 0.0):.2f}",
                f"{final:.2f}",
                settings.currency,
                o.created_at.isoformat() if o.created_at else "",
                o.delivered_at.isoformat() if o.delivered_at else "",
                o.expires_at.isoformat() if o.expires_at else "",
            ])
    data = buf.getvalue().encode("utf-8")
    await update.message.reply_document(
        document=io.BytesIO(data),
        filename=f"orders-{datetime.utcnow():%Y%m%d-%H%M}.csv",
        caption=f"📁 Exportado: {len(orders)} pedidos",
    )


# ---------- runtime config ----------

@admin_only
async def cmd_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    from bot.services.runtime_config_service import KEY_MAINTENANCE, set_value
    if not args:
        from bot.services.runtime_config_service import is_maintenance
        cur = is_maintenance()
        await update.message.reply_text(
            f"Modo mantenimiento actualmente: {'🛠 ON' if cur else '🟢 OFF'}\n"
            "Uso: /maintenance on | off"
        )
        return
    on = args[0].lower() in ("on", "1", "true", "yes", "si")
    with session_scope() as session:
        set_value(session, KEY_MAINTENANCE, "1" if on else "0")
    await update.message.reply_text(
        "🛠 Tienda en MANTENIMIENTO. Las compras nuevas están pausadas." if on
        else "🟢 Tienda activa de nuevo."
    )


@admin_only
async def cmd_set_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /setpayment `<texto>` — actualiza las instrucciones de pago en vivo.\n"
            "Usa `/setpayment off` para volver al texto del .env.",
            parse_mode="Markdown",
        )
        return
    from bot.services.runtime_config_service import KEY_PAYMENT, delete, set_value
    text = " ".join(args).strip()
    with session_scope() as session:
        if text.lower() in ("off", "reset", "default"):
            delete(session, KEY_PAYMENT)
            await update.message.reply_text("🔁 Instrucciones de pago restauradas al .env.")
        else:
            set_value(session, KEY_PAYMENT, text)
            await update.message.reply_text("💳 Instrucciones de pago actualizadas.")


@admin_only
async def cmd_set_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /setshop `<nombre>` — cambia el nombre que aparece en el bot. "
            "`/setshop off` para volver al .env.",
            parse_mode="Markdown",
        )
        return
    from bot.services.runtime_config_service import KEY_SHOP_NAME, delete, set_value
    text = " ".join(args).strip()
    with session_scope() as session:
        if text.lower() in ("off", "reset", "default"):
            delete(session, KEY_SHOP_NAME)
            await update.message.reply_text("🔁 Nombre de tienda restaurado al .env.")
        else:
            set_value(session, KEY_SHOP_NAME, text)
            await update.message.reply_text(f"🏪 Nombre actualizado a: {text}")


def build_addstock_conversation():
    """Devuelve el ConversationHandler para /addstock y /bulkstock."""
    from telegram.ext import CommandHandler

    return ConversationHandler(
        entry_points=[
            CommandHandler("addstock", cmd_add_stock),
            CommandHandler("bulkstock", cmd_add_stock),
        ],
        states={
            ASK_STOCK_LINES: [
                CommandHandler("done", stock_done),
                CommandHandler("cancel", stock_cancel),
                MessageHandler(
                    (filters.TEXT | filters.Document.ALL) & ~filters.COMMAND,
                    stock_collect,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", stock_cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )
