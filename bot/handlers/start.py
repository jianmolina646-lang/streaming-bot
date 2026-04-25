"""/start, /help y mensajes del menú principal."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.database import session_scope
from bot.db.models import Order, SupportMessage
from bot.handlers.catalog import show_catalog
from bot.handlers.orders import STATUS_LABELS, show_my_orders
from bot.keyboards import main_menu
from bot.services.faq_service import find_matching_faq, list_active_faqs
from bot.services.order_service import get_or_create_user, list_user_orders
from config import Settings

log = logging.getLogger(__name__)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _fmt_dt(value) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_chat is None or update.message is None:
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
        f"✨ *Bienvenido a {shop_name}*\n\n"
        f"Hola, *{user.first_name}*. Aquí puedes comprar tus cuentas de streaming "
        "de forma rápida, clara y segura.\n\n"
        "*¿Qué puedes hacer aquí?*\n"
        "• Ver el catálogo disponible\n"
        "• Revisar tu saldo y tus compras\n"
        "• Recibir tus credenciales en el chat\n"
        "• Pedir soporte o garantía si algo falla\n\n"
        "*Empieza así:*\n"
        "1. Entra a *🛍 Catálogo*\n"
        "2. Elige tu servicio y plan\n"
        "3. Paga con saldo o comprobante\n"
        "4. Recibe tu cuenta en el bot\n\n"
        "Si quieres la guía rápida completa, toca *🧭 Cómo comprar* o usa /tutorial."
    )
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ *Centro de ayuda*\n\n"
        "*Comandos principales*\n"
        "/start — Abrir el menú principal\n"
        "/catalogo — Ver servicios y planes disponibles\n"
        "/tutorial — Guía rápida para comprar\n"
        "/pedidos — Ver tus compras, estado y vencimientos\n"
        "/saldo — Ver tu saldo, créditos y movimientos\n"
        "/cupon `<CÓDIGO>` — Aplicar un cupón a la próxima compra\n"
        "/referidos — Ver tu link de referidos y comisiones\n"
        "/garantia `<order_id>` — Reportar un problema con una cuenta\n"
        "/faq — Preguntas frecuentes\n"
        "/soporte — Hablar con soporte\n"
        "/help — Ver esta ayuda\n\n"
        "*Ruta recomendada para comprar*\n"
        "1. Abre el catálogo\n"
        "2. Escoge el plan\n"
        "3. Revisa el total\n"
        "4. Paga con saldo o envía tu comprobante\n"
        "5. Recibe tus credenciales en el chat"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())


async def cmd_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    settings = _settings(context)
    text = (
        "🧭 *Tutorial de compra*\n\n"
        "*Paso 1.* Entra a *🛍 Catálogo* y elige una plataforma.\n"
        "*Paso 2.* Abre el plan que quieras comprar y revisa precio, duración y stock.\n"
        "*Paso 3.* Toca *🛒 Comprar ahora*.\n"
        "*Paso 4.* Elige cómo pagar:\n"
        "• *Saldo:* si ya tienes créditos cargados\n"
        "• *Manual:* si pagarás por Yape, Plin o transferencia\n"
        "*Paso 5.* Si pagas manual, envía tu comprobante en el chat.\n"
        "*Paso 6.* Cuando el admin apruebe, recibirás tu cuenta y fecha de vencimiento.\n\n"
        f"💡 *Consejo:* también puedes usar cupones con /cupon y revisar tu saldo en {settings.currency} con /saldo."
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
            REFERRAL_COMMISSION_PCT,
            count_referrals,
            ensure_ref_code,
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
        "Cuéntanos tu problema por este mismo chat y un administrador te responderá "
        "lo antes posible.\n\n"
        "Si tu compra ya fue entregada y la cuenta dejó de funcionar, también puedes "
        "usar /garantia `<order_id>`.\n\n"
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

        txs = list_transactions(session, user.id, limit=8)
        orders = list_user_orders(session, user.id, limit=3)
        bal = float(user.balance or 0.0)
        lines = [
            "💳 *Resumen de tu saldo*",
            "",
            f"Saldo disponible: *{bal:.2f} {settings.currency}*",
            f"Nivel VIP: *{int(user.vip_level or 0)}*",
            "",
            "Si quieres recargar, envía tu pago al admin y te acreditará el monto.",
        ]
        if txs:
            lines.extend(["", "*Últimos movimientos*"])
            kind_label = {
                "topup": "🟢 Recarga",
                "purchase": "🛒 Compra",
                "refund": "↩️ Reembolso",
                "adjust": "✏️ Ajuste",
                "referral": "🎁 Comisión por referido",
            }
            for t in txs:
                sign = "+" if t.amount >= 0 else "−"
                note = f" — {t.note}" if t.note else ""
                lines.append(
                    f"• {kind_label.get(t.kind, t.kind)}: {sign}{abs(t.amount):.2f} "
                    f"{settings.currency} ({t.created_at:%Y-%m-%d}){note}"
                )
        if orders:
            lines.extend(["", "*Tus compras más recientes*"])
            for o in orders:
                final_price = max(0.0, o.price - (o.discount_amount or 0.0))
                lines.append(
                    f"• Pedido *#{o.id}* — {o.plan.service.emoji} {o.plan.service.name} / "
                    f"{o.plan.name}"
                )
                lines.append(
                    f"  Estado: {STATUS_LABELS.get(o.status, o.status)} | "
                    f"Importe: {final_price:.2f} {settings.currency}"
                )
                lines.append(f"  Vence: {_fmt_dt(o.expires_at)}")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu()
    )


async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra al cliente las preguntas frecuentes."""
    if update.message is None:
        return
    with session_scope() as session:
        faqs = list_active_faqs(session)
        if not faqs:
            await update.message.reply_text(
                "Aún no hay preguntas frecuentes. Si necesitas ayuda, escríbenos por aquí.",
                reply_markup=main_menu(),
            )
            return
        lines = ["❓ *Preguntas frecuentes*", ""]
        for f in faqs:
            lines.append(f"*{f.question}*")
            lines.append(f"{f.answer}")
            lines.append("")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu()
    )


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
    if text.startswith("🧭") or "cómo comprar" in text or "como comprar" in text or "tutorial" in text:
        await cmd_tutorial(update, context)
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
    if text.startswith("🎁") or "referid" in text:
        await cmd_referrals(update, context)
        return
    if text.startswith("ℹ") or "ayuda" in text or "help" in text:
        await cmd_help(update, context)
        return

    settings = _settings(context)
    if update.effective_user.id in settings.admin_ids:
        return

    with session_scope() as session:
        faq = find_matching_faq(session, raw)
    if faq is not None:
        await update.message.reply_text(
            f"*{faq.question}*\n\n{faq.answer}\n\n"
            "_Si esto no resuelve tu duda, te leemos: déjanos un mensaje y "
            "un administrador te responde._",
            parse_mode="Markdown",
            reply_markup=main_menu(),
        )
        return

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
        "📨 Recibimos tu mensaje. Un administrador te responderá lo antes posible.",
        reply_markup=main_menu(),
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
