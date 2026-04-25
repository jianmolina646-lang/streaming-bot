"""/start, /help y mensajes del menú principal."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.database import session_scope
from bot.db.models import SupportMessage
from bot.handlers.catalog import show_catalog
from bot.handlers.orders import show_my_orders
from bot.keyboards import main_menu
from bot.services.faq_service import find_matching_faq, list_active_faqs
from bot.services.order_service import get_or_create_user
from config import Settings

log = logging.getLogger(__name__)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_chat is None:
        return
    args = context.args or []
    ref_code = (args[0].upper().strip() if args else "")
    with session_scope() as session:
        db_user = get_or_create_user(
            session,
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        if ref_code and db_user.referred_by_id is None:
            from bot.services.referral_service import attach_referral
            attach_referral(session, db_user, ref_code)
    settings = _settings(context)
    from bot.services.runtime_config_service import get_shop_name
    shop_name = get_shop_name(settings.shop_name)
    text = (
        f"👋 ¡Hola {user.first_name}!\n\n"
        f"Bienvenido a *{shop_name}*.\n"
        "Aquí puedes comprar suscripciones a tus plataformas de streaming favoritas "
        "de forma rápida y segura.\n\n"
        "Usa los botones de abajo para navegar."
    )
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Comandos disponibles:*\n"
        "/start — Menú principal\n"
        "/catalogo — Ver servicios disponibles\n"
        "/pedidos — Ver tus pedidos\n"
        "/saldo — Ver tu saldo y movimientos\n"
        "/cupon `<CÓDIGO>` — Aplicar cupón a tu próxima compra\n"
        "/referidos — Tu link de referidos y comisiones\n"
        "/garantia `<order_id>` — Reportar que tu cuenta dejó de funcionar\n"
        "/faq — Preguntas frecuentes\n"
        "/soporte — Contacto con un humano\n"
        "/help — Esta ayuda\n\n"
        "Para comprar: abre el catálogo, elige un servicio y un plan, y sigue "
        "las instrucciones de pago. Si tienes saldo, puedes pagar al instante."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())


async def cmd_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra al cliente su link de referidos y la comisión acumulada."""
    if update.message is None or update.effective_user is None:
        return
    settings = _settings(context)
    tg_user = update.effective_user
    me = await context.bot.get_me()
    bot_username = me.username
    with session_scope() as session:
        user = get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        from bot.services.referral_service import (
            count_referrals,
            ensure_ref_code,
            REFERRAL_COMMISSION_PCT,
            total_commission_earned,
        )
        code = ensure_ref_code(session, user)
        total_refs = count_referrals(session, user.id)
        earnings = total_commission_earned(session, user.id)
    link = f"https://t.me/{bot_username}?start={code}"
    text = (
        f"👥 *Tu programa de referidos*\n\n"
        f"Tu código: `{code}`\n"
        f"Tu link: {link}\n\n"
        f"📊 Has invitado: *{total_refs}* persona(s)\n"
        f"💰 Has ganado: *{earnings:.2f} {settings.currency}* en saldo\n\n"
        f"Cuando alguien entra con tu link y hace su primera compra, "
        f"recibes *{REFERRAL_COMMISSION_PCT:.0f}%* del valor en saldo "
        "para gastar en tu próxima compra."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    admins = ", ".join(str(a) for a in settings.admin_ids) or "—"
    text = (
        "💬 *Soporte*\n\n"
        "Si tienes algún problema con tu pedido, escríbenos por aquí mismo. "
        "Un administrador te responderá lo antes posible.\n\n"
        f"_IDs de administradores configurados: {admins}_"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra al cliente su saldo y últimos movimientos."""
    if update.effective_user is None or update.message is None:
        return
    settings = _settings(context)
    tg_user = update.effective_user
    with session_scope() as session:
        user = get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        from bot.services.wallet_service import list_transactions
        txs = list_transactions(session, user.id, limit=10)
        bal = float(user.balance or 0.0)
        lines = [
            f"💰 *Tu saldo:* {bal:.2f} {settings.currency}",
            "",
            "Para recargar, contacta al admin con tu pago "
            "(Yape/Plin/transferencia) y él te acreditará el monto.",
        ]
        if txs:
            lines.append("")
            lines.append("*Últimos movimientos:*")
            kind_label = {
                "topup": "🟢 Recarga",
                "purchase": "🛒 Compra",
                "refund": "↩️ Reembolso",
                "adjust": "✏️ Ajuste",
                "referral": "🎁 Comisión referido",
            }
            for t in txs:
                sign = "+" if t.amount >= 0 else "−"
                lines.append(
                    f"{kind_label.get(t.kind, t.kind)}: {sign}{abs(t.amount):.2f} "
                    f"{settings.currency} ({t.created_at:%Y-%m-%d})"
                )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra al cliente las preguntas frecuentes."""
    with session_scope() as session:
        faqs = list_active_faqs(session)
        if not faqs:
            await update.message.reply_text(
                "Aún no hay preguntas frecuentes. Si necesitas ayuda, escríbenos por aquí."
            )
            return
        lines = ["❓ *Preguntas frecuentes*", ""]
        for f in faqs:
            lines.append(f"*{f.question}*")
            lines.append(f"{f.answer}")
            lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch para los botones del teclado y soporte automatizado.

    - Si el mensaje coincide con un botón del teclado, abre la sección correspondiente.
    - Si coincide con palabras clave de un FAQ, responde automáticamente.
    - Si no, lo trata como mensaje de soporte y lo reenvía a los administradores.
    """
    if update.message is None or update.message.text is None or update.effective_user is None:
        return
    raw = update.message.text.strip()
    text = raw.lower()
    if text.startswith("🛍") or "catálogo" in text or "catalogo" in text:
        await show_catalog(update, context)
        return
    if text.startswith("📦") or "pedidos" in text:
        await show_my_orders(update, context)
        return
    if text.startswith("💰") or "saldo" in text or "credit" in text:
        await cmd_saldo(update, context)
        return
    if text.startswith("❓") or text.startswith("faq") or "preguntas" in text:
        await cmd_faq(update, context)
        return
    if text.startswith("💬") or "soporte" in text:
        await cmd_support(update, context)
        return
    if "referid" in text:
        await cmd_referrals(update, context)
        return
    if text.startswith("ℹ") or "ayuda" in text or "help" in text:
        await cmd_help(update, context)
        return

    # No routear mensajes de admins (evita ecos al responder soporte).
    settings = _settings(context)
    if update.effective_user.id in settings.admin_ids:
        return

    # Soporte automatizado: ¿coincide con algún FAQ?
    with session_scope() as session:
        faq = find_matching_faq(session, raw)
    if faq is not None:
        await update.message.reply_text(
            f"*{faq.question}*\n\n{faq.answer}\n\n"
            "_Si esto no resuelve tu duda, te leemos: déjanos un mensaje y "
            "un administrador te responde._",
            parse_mode="Markdown",
        )
        return

    # Mensaje libre: lo guardamos y lo reenviamos al(los) admin(s).
    tg_user = update.effective_user
    with session_scope() as session:
        user = get_or_create_user(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        session.add(SupportMessage(user_id=user.id, message_text=raw))

    await update.message.reply_text(
        "📨 Recibimos tu mensaje. Un administrador te responderá lo antes posible."
    )

    label = (
        f"📬 *Mensaje de soporte*\n"
        f"De: {tg_user.full_name or '—'} (@{tg_user.username or '—'})\n"
        f"Telegram ID: `{tg_user.id}`\n\n"
        f"_Para responder:_ `/reply {tg_user.id} tu respuesta aquí`"
    )
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, label, parse_mode="Markdown")
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception:
            log.exception("No se pudo reenviar mensaje de soporte al admin %s", admin_id)
