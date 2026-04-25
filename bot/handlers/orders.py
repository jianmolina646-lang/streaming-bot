"""Flujo de pedidos del lado del cliente."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.database import session_scope
from bot.db.models import Coupon, Order, StockItem, WalletTransaction
from bot.keyboards import (
    admin_review_keyboard,
    main_menu,
    order_pending_keyboard,
    payment_method_keyboard,
    review_keyboard,
)
from bot.services.catalog_service import get_plan, take_stock
from bot.services.coupon_service import (
    compute_discount,
    consume as consume_coupon,
    get_coupon_by_code,
    is_valid as coupon_is_valid,
)
from bot.services.order_service import (
    create_order,
    get_or_create_user,
    get_order,
    list_user_orders,
)
from bot.services.referral_service import maybe_pay_commission
from bot.services.runtime_config_service import (
    get_payment_instructions,
    is_maintenance,
)
from bot.services.wallet_service import add_balance, get_balance
from config import Settings

log = logging.getLogger(__name__)

# Estados legibles para el usuario.
STATUS_LABELS = {
    Order.STATUS_PENDING_PAYMENT: "⏳ Esperando comprobante",
    Order.STATUS_AWAITING_REVIEW: "🔍 En revisión por admin",
    Order.STATUS_APPROVED: "✅ Aprobado",
    Order.STATUS_REJECTED: "🚫 Rechazado",
    Order.STATUS_DELIVERED: "📦 Entregado",
    Order.STATUS_EXPIRED: "⌛ Vencido",
    Order.STATUS_REFUNDED: "↩️ Reembolsado",
}

# VIP descuentos por nivel.
VIP_DISCOUNTS = {0: 0.0, 1: 5.0, 2: 10.0}


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _vip_discount_pct(vip_level: int) -> float:
    return VIP_DISCOUNTS.get(int(vip_level or 0), 0.0)


def _compute_final_price(
    base_price: float, vip_level: int, coupon: Coupon | None
) -> tuple[float, float, float, float]:
    """Devuelve (final, vip_off, coupon_off, total_off)."""
    vip_pct = _vip_discount_pct(vip_level)
    vip_off = round(base_price * (vip_pct / 100.0), 2) if vip_pct else 0.0
    after_vip = max(0.0, base_price - vip_off)
    coupon_off = compute_discount(coupon, after_vip) if coupon else 0.0
    final = max(0.0, round(after_vip - coupon_off, 2))
    return final, vip_off, coupon_off, vip_off + coupon_off


def _pop_pending_coupon(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get("pending_coupon")


async def start_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `buy:<plan_id>` — muestra opciones de pago (saldo o manual)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    try:
        plan_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    if is_maintenance():
        await query.edit_message_text(
            "🛠 Tienda en mantenimiento. Vuelve a intentar más tarde."
        )
        return

    settings = _settings(context)
    tg_user = update.effective_user
    pending_coupon_code = _pop_pending_coupon(context)

    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None or not plan.is_active:
            await query.edit_message_text("Este plan ya no está disponible.")
            return
        user = get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        if user.is_blocked:
            await query.edit_message_text(
                "⛔ Tu cuenta está bloqueada para nuevas compras. Contacta a soporte."
            )
            return
        balance = get_balance(session, user)
        coupon = (
            get_coupon_by_code(session, pending_coupon_code)
            if pending_coupon_code
            else None
        )
        if coupon is not None and not coupon_is_valid(coupon):
            coupon = None
            context.user_data.pop("pending_coupon", None)
        final, vip_off, coupon_off, total_off = _compute_final_price(
            plan.price, user.vip_level, coupon
        )
        plan_name = plan.name
        service_name = plan.service.name
        service_emoji = plan.service.emoji

    lines = [
        f"🛒 *{service_emoji} {service_name} — {plan_name}*",
        f"💵 Precio: *{plan.price:.2f} {settings.currency}*",
    ]
    if vip_off > 0:
        lines.append(
            f"⭐ Descuento VIP: −{vip_off:.2f} {settings.currency}"
        )
    if coupon is not None and coupon_off > 0:
        lines.append(
            f"🎟 Cupón `{coupon.code}`: −{coupon_off:.2f} {settings.currency}"
        )
    if total_off > 0:
        lines.append(f"✅ *Total: {final:.2f} {settings.currency}*")
    lines.append(f"💰 Tu saldo: *{balance:.2f} {settings.currency}*")
    lines.append("")
    lines.append("Elige cómo pagar:")
    text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=payment_method_keyboard(plan_id, balance, final, settings.currency),
        parse_mode="Markdown",
    )


def _consume_coupon_and_set_on_order(
    session, order: Order, coupon: Coupon | None, coupon_off: float
) -> None:
    if coupon is None or coupon_off <= 0:
        return
    order.coupon_id = coupon.id
    consume_coupon(session, coupon)


async def cb_pay_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `pay:manual:<plan_id>` — flujo de pago tradicional con comprobante."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    try:
        plan_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return

    if is_maintenance():
        await query.edit_message_text("🛠 Tienda en mantenimiento.")
        return

    settings = _settings(context)
    tg_user = update.effective_user
    pending_coupon_code = _pop_pending_coupon(context)

    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None or not plan.is_active:
            await query.edit_message_text("Este plan ya no está disponible.")
            return
        user = get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        if user.is_blocked:
            await query.edit_message_text("⛔ Tu cuenta está bloqueada.")
            return
        coupon = (
            get_coupon_by_code(session, pending_coupon_code)
            if pending_coupon_code
            else None
        )
        if coupon is not None and not coupon_is_valid(coupon):
            coupon = None
            context.user_data.pop("pending_coupon", None)
        final, vip_off, coupon_off, total_off = _compute_final_price(
            plan.price, user.vip_level, coupon
        )
        order = create_order(session, user, plan)
        order.payment_method = Order.PAY_METHOD_MANUAL
        order.discount_amount = round(total_off, 2)
        order.price = plan.price  # mantenemos precio base para reportes
        _consume_coupon_and_set_on_order(session, order, coupon, coupon_off)
        # Limpiamos el cupón después de usarlo.
        if coupon is not None:
            context.user_data.pop("pending_coupon", None)
        order_id = order.id
        plan_name = plan.name
        service_name = plan.service.name
        service_emoji = plan.service.emoji

    context.user_data["awaiting_proof_for_order"] = order_id

    pay_text = get_payment_instructions(settings.payment_instructions)
    detail_lines = [
        f"🧾 *Pedido #{order_id} creado*",
        "",
        f"{service_emoji} *{service_name} — {plan_name}*",
        f"💵 Precio base: *{plan.price:.2f} {settings.currency}*",
    ]
    if vip_off > 0:
        detail_lines.append(f"⭐ Descuento VIP: −{vip_off:.2f}")
    if coupon_off > 0:
        detail_lines.append(f"🎟 Cupón: −{coupon_off:.2f}")
    detail_lines.append(f"➡️ *Total a pagar: {final:.2f} {settings.currency}*")
    detail_lines.append("")
    detail_lines.append(pay_text)
    detail_lines.append("")
    detail_lines.append(
        "📤 Cuando completes el pago, *envía aquí mismo una foto o captura del "
        "comprobante*."
    )
    await query.edit_message_text(
        "\n".join(detail_lines),
        reply_markup=order_pending_keyboard(order_id),
        parse_mode="Markdown",
    )


async def cb_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `pay:wallet:<plan_id>` — compra instantánea con saldo."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    try:
        plan_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return

    if is_maintenance():
        await query.edit_message_text("🛠 Tienda en mantenimiento.")
        return

    settings = _settings(context)
    tg_user = update.effective_user
    pending_coupon_code = _pop_pending_coupon(context)
    delivered_text: str | None = None
    plan_label = ""
    expires_at: datetime | None = None
    order_id: int | None = None
    final_price = 0.0
    low_stock_info: tuple[str, int] | None = None
    error: str | None = None
    commission_paid = 0.0
    referrer_tg_id: int | None = None

    with session_scope() as session:
        plan = get_plan(session, plan_id)
        if plan is None or not plan.is_active:
            error = "Este plan ya no está disponible."
        else:
            user = get_or_create_user(
                session,
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name,
            )
            if user.is_blocked:
                error = "⛔ Tu cuenta está bloqueada para nuevas compras."
            else:
                coupon = (
                    get_coupon_by_code(session, pending_coupon_code)
                    if pending_coupon_code
                    else None
                )
                if coupon is not None and not coupon_is_valid(coupon):
                    coupon = None
                    context.user_data.pop("pending_coupon", None)
                final, vip_off, coupon_off, total_off = _compute_final_price(
                    plan.price, user.vip_level, coupon
                )
                if user.balance < final:
                    error = (
                        f"Saldo insuficiente. Necesitas {final:.2f} "
                        f"{settings.currency} y tienes {user.balance:.2f}."
                    )
                else:
                    stock_item = take_stock(session, plan.id)
                    if stock_item is None:
                        error = "⛔ Sin stock disponible. Intenta más tarde."
                    else:
                        now = datetime.utcnow()
                        order = create_order(session, user, plan)
                        order.payment_method = Order.PAY_METHOD_WALLET
                        order.status = Order.STATUS_DELIVERED
                        order.discount_amount = round(total_off, 2)
                        order.price = plan.price
                        order.delivered_credentials = stock_item.credentials
                        order.delivered_at = now
                        order.expires_at = now + timedelta(days=plan.duration_days)
                        _consume_coupon_and_set_on_order(
                            session, order, coupon, coupon_off
                        )
                        if coupon is not None:
                            context.user_data.pop("pending_coupon", None)
                        add_balance(
                            session,
                            user,
                            -final,
                            kind=WalletTransaction.KIND_PURCHASE,
                            note=f"Compra pedido #{order.id}",
                            related_order_id=order.id,
                        )
                        commission_paid = maybe_pay_commission(session, order)
                        if commission_paid > 0 and user.referred_by_id is not None:
                            from bot.db.models import User as UserModel
                            ref_user = session.get(UserModel, user.referred_by_id)
                            if ref_user is not None:
                                referrer_tg_id = ref_user.telegram_id
                        delivered_text = stock_item.credentials
                        plan_label = f"{plan.service.emoji} {plan.service.name} — {plan.name}"
                        expires_at = order.expires_at
                        order_id = order.id
                        final_price = final
                        order.review_requested_at = now
                        remaining = session.scalar(
                            select(func.count(StockItem.id)).where(
                                StockItem.plan_id == plan.id,
                                StockItem.is_sold.is_(False),
                            )
                        )
                        if remaining is not None and remaining <= 2:
                            low_stock_info = (plan_label, int(remaining))

    if error is not None:
        await query.edit_message_text(error)
        return

    msg = (
        f"🎉 *¡Compra realizada!*\n\n"
        f"Pedido: *#{order_id}*\n"
        f"Producto: {plan_label}\n"
        f"Pagaste: *{final_price:.2f} {settings.currency}*\n"
        f"Vence: {expires_at:%Y-%m-%d}\n\n"
        f"*Credenciales:*\n```\n{delivered_text}\n```\n\n"
        "⚠️ No compartas estos datos. Si algo falla usa /garantia "
        f"{order_id} para abrir un ticket."
    )
    await query.edit_message_text(msg, parse_mode="Markdown")

    # Solicitud de calificación.
    if order_id is not None:
        try:
            await context.bot.send_message(
                tg_user.id,
                "🌟 ¿Cómo te fue con esta compra? Tu opinión nos ayuda.",
                reply_markup=review_keyboard(order_id),
            )
        except Exception:
            log.exception("No se pudo pedir reseña")

    # Aviso a admins: venta por saldo.
    notify_admin = (
        f"💰 *Venta por saldo*\n"
        f"Pedido #{order_id} — {plan_label} — {final_price:.2f} {settings.currency}\n"
        f"Cliente: {tg_user.full_name or '—'} (@{tg_user.username or '—'}) — `{tg_user.id}`"
    )
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, notify_admin, parse_mode="Markdown")
        except Exception:
            log.exception("No se pudo notificar al admin %s", admin_id)

    if low_stock_info is not None:
        plan_label2, remaining = low_stock_info
        alert = (
            f"⚠️ *Stock bajo*: {plan_label2} — quedan *{remaining}*.\n"
            "Usa /addstock para reponer."
        )
        for admin_id in settings.admin_ids:
            try:
                await context.bot.send_message(admin_id, alert, parse_mode="Markdown")
            except Exception:
                log.exception("No se pudo enviar aviso de stock bajo a %s", admin_id)

    # Notificar al referidor de la comisión cobrada.
    if commission_paid > 0 and referrer_tg_id is not None:
        try:
            await context.bot.send_message(
                referrer_tg_id,
                f"🎁 ¡Tu referido hizo su primera compra! Acabas de ganar "
                f"*+{commission_paid:.2f} {settings.currency}* en saldo.\n"
                "Mira tu /saldo para usarlo en tu próxima compra.",
                parse_mode="Markdown",
            )
        except Exception:
            log.exception("No se pudo avisar al referidor")


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        order_id = int(query.data.split(":")[2])
    except (ValueError, IndexError):
        return
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await query.edit_message_text("Pedido no encontrado.")
            return
        if order.status not in (Order.STATUS_PENDING_PAYMENT, Order.STATUS_AWAITING_REVIEW):
            await query.edit_message_text(
                f"No se puede cancelar este pedido (estado: "
                f"{STATUS_LABELS.get(order.status, order.status)})."
            )
            return
        order.status = Order.STATUS_REJECTED
        order.admin_note = "Cancelado por el cliente."
    if context.user_data.get("awaiting_proof_for_order") == order_id:
        context.user_data.pop("awaiting_proof_for_order", None)
    await query.edit_message_text(f"❌ Pedido #{order_id} cancelado.")


async def receive_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recibe foto/documento como comprobante de pago y notifica a los admins."""
    if update.message is None or update.effective_user is None:
        return
    order_id = context.user_data.get("awaiting_proof_for_order")
    if not order_id:
        return

    msg = update.message
    file_id: str | None = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
    else:
        await msg.reply_text(
            "Por favor envía una *foto* o *documento* con el comprobante.",
            parse_mode="Markdown",
        )
        return

    settings = _settings(context)
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None:
            await msg.reply_text("No encontré tu pedido.")
            context.user_data.pop("awaiting_proof_for_order", None)
            return
        if order.status != Order.STATUS_PENDING_PAYMENT:
            await msg.reply_text(
                f"Tu pedido ya está en estado: "
                f"{STATUS_LABELS.get(order.status, order.status)}"
            )
            return
        order.status = Order.STATUS_AWAITING_REVIEW
        order.proof_file_id = file_id
        order.proof_message_id = msg.message_id
        plan_name = order.plan.name
        service_name = order.plan.service.name
        service_emoji = order.plan.service.emoji
        final_price = max(0.0, order.price - (order.discount_amount or 0.0))
        username = order.user.username or "—"
        full_name = order.user.full_name or "—"
        client_chat_id = update.effective_chat.id

    context.user_data.pop("awaiting_proof_for_order", None)

    await msg.reply_text(
        f"✅ Comprobante recibido para el pedido #{order_id}.\n"
        "Tu pago está siendo revisado. Te avisamos cuando esté listo."
    )

    caption = (
        f"🆕 *Nuevo pedido para revisar*\n\n"
        f"Pedido: *#{order_id}*\n"
        f"Cliente: {full_name} (@{username}) — `{update.effective_user.id}`\n"
        f"Producto: {service_emoji} {service_name} — {plan_name}\n"
        f"Total: *{final_price:.2f} {settings.currency}*"
    )
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, caption, parse_mode="Markdown")
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=client_chat_id,
                message_id=msg.message_id,
            )
            await context.bot.send_message(
                admin_id,
                f"Acciones para el pedido #{order_id}:",
                reply_markup=admin_review_keyboard(order_id),
            )
        except Exception:
            log.exception("No se pudo notificar al admin %s", admin_id)


async def show_my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    with session_scope() as session:
        user = get_or_create_user(
            session,
            telegram_id=update.effective_user.id,
            username=update.effective_user.username,
            full_name=update.effective_user.full_name,
        )
        orders = list_user_orders(session, user.id)
        if not orders:
            text = "📦 Aún no tienes pedidos."
        else:
            lines = ["📦 *Tus últimos pedidos:*", ""]
            settings = _settings(context)
            for o in orders:
                price = max(0.0, o.price - (o.discount_amount or 0.0))
                lines.append(
                    f"#{o.id} — {o.plan.service.emoji} {o.plan.service.name} "
                    f"{o.plan.name} — {price:.2f} {settings.currency} — "
                    f"{STATUS_LABELS.get(o.status, o.status)}"
                )
            text = "\n".join(lines)
    if update.message is not None:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu()
        )
    elif update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")


async def cmd_apply_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/cupon CODIGO` — aplica un cupón a la próxima compra."""
    if update.message is None:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /cupon `<CÓDIGO>` — aplica un cupón a tu próxima compra.",
            parse_mode="Markdown",
        )
        return
    code = args[0].upper().strip()
    with session_scope() as session:
        coupon = get_coupon_by_code(session, code)
        if coupon is None or not coupon_is_valid(coupon):
            await update.message.reply_text(
                "❌ Cupón inválido o ya expirado."
            )
            return
        if coupon.discount_percent > 0:
            desc = f"{coupon.discount_percent:.0f}% de descuento"
        else:
            desc = f"{coupon.discount_amount:.2f} de descuento"
    context.user_data["pending_coupon"] = code
    await update.message.reply_text(
        f"🎟 Cupón `{code}` aplicado: {desc}. Se usará en tu próxima compra.",
        parse_mode="Markdown",
    )


async def cmd_warranty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/garantia <order_id> [mensaje]` — abre un ticket de garantía."""
    if update.message is None or update.effective_user is None:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Uso: /garantia `<order_id>` `[descripción del problema]`\n\n"
            "Ejemplo: `/garantia 42 No me deja entrar, dice contraseña incorrecta`",
            parse_mode="Markdown",
        )
        return
    try:
        order_id = int(args[0])
    except ValueError:
        await update.message.reply_text("order_id inválido.")
        return
    description = " ".join(args[1:]) or None
    settings = _settings(context)
    tg_user = update.effective_user
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None or order.user.telegram_id != tg_user.id:
            await update.message.reply_text("Pedido no encontrado.")
            return
        if order.status not in (Order.STATUS_DELIVERED, Order.STATUS_APPROVED):
            await update.message.reply_text(
                "Solo puedes pedir garantía de pedidos entregados."
            )
            return
        from bot.services.warranty_service import open_ticket
        ticket = open_ticket(session, order.user.id, order.id, description)
        ticket_id = ticket.id
        plan_label = f"{order.plan.service.emoji} {order.plan.service.name} — {order.plan.name}"
        cred = (order.delivered_credentials or "").split("\n")[0][:80]
        username = tg_user.username or tg_user.full_name or str(tg_user.id)

    await update.message.reply_text(
        f"📨 Ticket #{ticket_id} abierto. El admin lo revisará pronto."
    )
    body = (
        f"🚨 *Ticket de garantía #{ticket_id}*\n\n"
        f"Pedido: #{order_id}\n"
        f"Cliente: @{username} (`{tg_user.id}`)\n"
        f"Producto: {plan_label}\n"
        f"Credencial: `{cred}`\n"
        f"Mensaje: {description or '(sin descripción)'}\n\n"
        f"Acciones:\n"
        f"• Reponer: `/replace {order_id}`\n"
        f"• Reembolsar: `/refund {order_id}`\n"
        f"• Marcar resuelto: `/resolveticket {ticket_id}`"
    )
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, body, parse_mode="Markdown")
        except Exception:
            log.exception("No se pudo avisar al admin %s del ticket", admin_id)


async def cb_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `review:<order_id>:<rating>` — guarda calificación 1-5 (0=saltar)."""
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    try:
        _, oid_str, rating_str = query.data.split(":")
        order_id = int(oid_str)
        rating = int(rating_str)
    except (ValueError, IndexError):
        return
    if rating == 0:
        await query.edit_message_text("Gracias 🙏")
        return
    if rating < 1 or rating > 5:
        return
    with session_scope() as session:
        order = get_order(session, order_id)
        if order is None or order.user.telegram_id != update.effective_user.id:
            return
        from bot.services.review_service import (
            add_review,
            get_review_for_order,
        )
        existing = get_review_for_order(session, order.id)
        if existing is not None:
            existing.rating = rating
        else:
            add_review(session, order.id, order.user.id, rating, None)
    msg = "🙏 ¡Gracias por tu calificación!" + (
        " Si tienes algún detalle, puedes mandarlo con /soporte." if rating <= 3 else ""
    )
    await query.edit_message_text(msg)
