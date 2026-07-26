"""Panel guiado de Netflix para administradores, sin IDs manuales."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters,
)

from bot.db.database import session_scope
from bot.db.models import AutomationAgent, AutomationJob, Order, Plan, Service, StockItem
from bot.services.automation_service import AUTOMATION_STOCK_TAG, create_profile_job
from bot.services.catalog_service import add_plan, add_service

ADD_EMAIL, TEST_NAME, TEST_PIN, CUSTOMER_NAME, CUSTOMER_PIN = range(5)
EMAIL_RE = re.compile(r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$")


def _settings(context):
    return context.application.bot_data["settings"]


async def _authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user and user.id in _settings(context).admin_ids:
        return True
    if update.callback_query:
        await update.callback_query.answer("Solo administradores.", show_alert=True)
    elif update.message:
        await update.message.reply_text("⛔ Solo administradores.")
    return False


def menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Agregar cuenta Netflix", callback_data="nfx:add")],
        [
            InlineKeyboardButton("📧 Ver cuentas", callback_data="nfx:list"),
            InlineKeyboardButton("🧪 Hacer prueba", callback_data="nfx:test"),
        ],
        [InlineKeyboardButton("🤖 Estado del agente", callback_data="nfx:status")],
    ])


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    text = "🎬 *Panel de Netflix*\n\nAdministra cuentas y pruebas sin escribir IDs."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=menu_markup()
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=menu_markup())
    return ConversationHandler.END


def _ensure_plan(session) -> Plan:
    service = session.scalar(
        select(Service).where(func.lower(Service.name) == "netflix").limit(1)
    )
    if service is None:
        service = add_service(
            session, "Netflix", "🎬", "Perfiles preparados por el agente local."
        )
    else:
        service.is_active = True
    plan = session.scalar(
        select(Plan).where(
            Plan.service_id == service.id, Plan.is_active.is_(True)
        ).order_by(Plan.id).limit(1)
    )
    if plan is None:
        plan = add_plan(
            session, service.id, "Perfil Netflix 30 días", 30, 10.0,
            "Perfil individual con PIN.",
        )
    return plan


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📧 *Agregar cuenta Netflix*\n\n"
        "Escribe el correo exacto conectado en Mail Control.\n"
        "No envíes la contraseña.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancelar", callback_data="nfx:menu")
        ]]),
    )
    return ADD_EMAIL


async def save_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    email = (update.message.text or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        await update.message.reply_text("Correo inválido. Inténtalo nuevamente.")
        return ADD_EMAIL
    with session_scope() as session:
        duplicate = session.scalar(
            select(StockItem).where(func.lower(StockItem.credentials) == email).limit(1)
        )
        if duplicate:
            await update.message.reply_text(
                "ℹ️ Esa cuenta ya estaba registrada.", reply_markup=menu_markup()
            )
            return ConversationHandler.END
        plan = _ensure_plan(session)
        session.add(StockItem(
            plan_id=plan.id, credentials=email, tag=AUTOMATION_STOCK_TAG, is_sold=False
        ))
    await update.message.reply_text(
        "✅ *Cuenta preparada*\n\n"
        "• Producto y plan verificados\n"
        "• Cuenta marcada para el agente\n"
        "• Contraseña no almacenada\n\n"
        "Ya está disponible en el catálogo.",
        parse_mode="Markdown", reply_markup=menu_markup(),
    )
    return ConversationHandler.END


def _mask(value: str) -> str:
    local, _, domain = value.partition("@")
    return f"{local[:2]}•••@{domain}" if domain else "Cuenta Netflix"


async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    with session_scope() as session:
        items = list(session.scalars(
            select(StockItem).join(Plan).join(Service).where(
                func.lower(Service.name) == "netflix",
                StockItem.tag == AUTOMATION_STOCK_TAG,
            ).order_by(StockItem.id.desc()).limit(30)
        ))
    lines = ["📧 *Cuentas Netflix*", ""]
    lines.extend(
        f"{'🔴' if item.is_sold else '🟢'} {_mask(item.credentials)} · "
        f"{'Utilizada' if item.is_sold else 'Disponible'}"
        for item in items
    )
    if not items:
        lines.append("Todavía no hay cuentas registradas.")
    await update.callback_query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("← Volver", callback_data="nfx:menu")
        ]]),
    )
    return ConversationHandler.END


async def agent_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    with session_scope() as session:
        agents = list(session.scalars(select(AutomationAgent).order_by(AutomationAgent.name)))
        queued = session.scalar(select(func.count(AutomationJob.id)).where(
            AutomationJob.status == AutomationJob.STATUS_QUEUED
        )) or 0
    lines = ["🤖 *Estado del agente*", ""]
    lines.extend(
        f"{'🟢' if a.is_active else '🔴'} {a.name} · "
        f"{'simulación' if a.dry_run else 'real'}"
        for a in agents
    )
    if not agents:
        lines.append("🔴 Ningún agente conectado.")
    lines.append(f"\nTrabajos esperando: {queued}")
    await update.callback_query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("← Volver", callback_data="nfx:menu")
        ]]),
    )
    return ConversationHandler.END


async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    with session_scope() as session:
        orders = list(session.scalars(
            select(Order).join(Plan).join(Service).where(
                func.lower(Service.name) == "netflix",
                Order.status.in_([
                    Order.STATUS_PENDING_PAYMENT, Order.STATUS_AWAITING_REVIEW,
                    Order.STATUS_APPROVED,
                ]),
            ).options(joinedload(Order.user)).order_by(Order.created_at.desc()).limit(10)
        ))
    if not orders:
        await update.callback_query.edit_message_text(
            "🧪 *Hacer prueba*\n\n"
            "No hay pedidos Netflix pendientes. Realiza un pedido desde el catálogo "
            "y vuelve a este botón.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Volver", callback_data="nfx:menu")
            ]]),
        )
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(
        f"Pedido #{o.id} · {o.user.full_name or o.user.username or 'Cliente'}",
        callback_data=f"nfx:order:{o.id}",
    )] for o in orders]
    keyboard.append([InlineKeyboardButton("← Volver", callback_data="nfx:menu")])
    await update.callback_query.edit_message_text(
        "🧪 *Selecciona el pedido*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def select_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    order_id = int(update.callback_query.data.rsplit(":", 1)[1])
    with session_scope() as session:
        order = session.get(Order, order_id)
        items = list(session.scalars(select(StockItem).where(
            StockItem.plan_id == order.plan_id,
            StockItem.is_sold.is_(False),
            StockItem.tag == AUTOMATION_STOCK_TAG,
        ).order_by(StockItem.id).limit(20))) if order else []
    if not items:
        await update.callback_query.edit_message_text(
            "No hay una cuenta disponible para este pedido.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Volver", callback_data="nfx:menu")
            ]]),
        )
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(
        _mask(item.credentials), callback_data=f"nfx:stock:{order_id}:{item.id}"
    )] for item in items]
    await update.callback_query.edit_message_text(
        "📧 *Elige la cuenta*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def select_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    _, _, order_id, stock_id = update.callback_query.data.split(":")
    context.user_data["nfx_order_id"] = int(order_id)
    context.user_data["nfx_stock_id"] = int(stock_id)
    await update.callback_query.edit_message_text("👤 Escribe el nombre del perfil.")
    return TEST_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name or len(name) > 80:
        await update.message.reply_text("Escribe un nombre de 1 a 80 caracteres.")
        return TEST_NAME
    context.user_data["nfx_profile_name"] = name
    await update.message.reply_text("🔐 Escribe el PIN de 4 números.")
    return TEST_PIN


async def receive_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = (update.message.text or "").strip()
    if not (pin.isdigit() and len(pin) == 4):
        await update.message.reply_text("El PIN debe tener exactamente 4 números.")
        return TEST_PIN
    settings = _settings(context)
    with session_scope() as session:
        order = session.get(Order, context.user_data.get("nfx_order_id"))
        item = session.get(StockItem, context.user_data.get("nfx_stock_id"))
        if not order or not item:
            await update.message.reply_text("Pedido o cuenta no disponibles.")
            return ConversationHandler.END
        try:
            create_profile_job(
                session, order=order, stock_item=item,
                encryption_key=settings.agent_encryption_key,
                profile_name=context.user_data["nfx_profile_name"], profile_pin=pin,
            )
        except ValueError as exc:
            await update.message.reply_text(str(exc), reply_markup=menu_markup())
            return ConversationHandler.END
        item.is_sold = True
    context.user_data.pop("nfx_order_id", None)
    context.user_data.pop("nfx_stock_id", None)
    context.user_data.pop("nfx_profile_name", None)
    await update.message.reply_text(
        "✅ *Prueba enviada al agente*\n\n"
        "Netflix se abrirá en la computadora. El PIN quedó cifrado.",
        parse_mode="Markdown", reply_markup=menu_markup(),
    )
    return ConversationHandler.END


async def start_customer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    order_id = int(update.callback_query.data.rsplit(":", 1)[1])
    with session_scope() as session:
        order = session.get(Order, order_id)
        valid = bool(
            order and update.effective_user
            and order.user.telegram_id == update.effective_user.id
            and order.status == Order.STATUS_APPROVED
            and order.automation_stock_id
        )
    if not valid:
        await update.callback_query.answer(
            "Este pedido no está disponible para tu cuenta.", show_alert=True
        )
        return ConversationHandler.END
    await update.callback_query.answer()
    context.user_data["nfx_customer_order_id"] = order_id
    await update.callback_query.edit_message_text(
        "👤 *Configura tu perfil*\n\nEscribe el nombre que deseas usar.",
        parse_mode="Markdown",
    )
    return CUSTOMER_NAME


async def customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name or len(name) > 80:
        await update.message.reply_text("Escribe un nombre de 1 a 80 caracteres.")
        return CUSTOMER_NAME
    context.user_data["nfx_customer_name"] = name
    await update.message.reply_text(
        "🔐 Ahora escribe un PIN de exactamente 4 números.\n"
        "El PIN será cifrado y no aparecerá en registros."
    )
    return CUSTOMER_PIN


async def customer_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pin = (update.message.text or "").strip()
    if not (pin.isdigit() and len(pin) == 4):
        await update.message.reply_text("El PIN debe tener exactamente 4 números.")
        return CUSTOMER_PIN
    order_id = context.user_data.get("nfx_customer_order_id")
    settings = _settings(context)
    with session_scope() as session:
        order = session.get(Order, order_id)
        if (
            not order or not update.effective_user
            or order.user.telegram_id != update.effective_user.id
            or order.status != Order.STATUS_APPROVED
            or not order.automation_stock_id
        ):
            await update.message.reply_text("Este pedido ya no puede configurarse.")
            return ConversationHandler.END
        item = session.get(StockItem, order.automation_stock_id)
        if not item:
            await update.message.reply_text("La cuenta reservada ya no está disponible.")
            return ConversationHandler.END
        try:
            create_profile_job(
                session, order=order, stock_item=item,
                encryption_key=settings.agent_encryption_key,
                profile_name=context.user_data["nfx_customer_name"],
                profile_pin=pin,
            )
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return ConversationHandler.END
        order.admin_note = "Perfil configurado por el cliente y enviado al agente."
    context.user_data.pop("nfx_customer_order_id", None)
    context.user_data.pop("nfx_customer_name", None)
    await update.message.reply_text(
        "✅ *Configuración recibida*\n\n"
        "Estamos creando tu perfil. Te avisaremos cuando quede verificado.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def reconfigure_existing(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Recupera pedidos creados por la versión anterior al flujo de preferencias."""
    if not await _authorized(update, context):
        return ConversationHandler.END
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Uso: /reconfigurarperfil <número de pedido>")
        return ConversationHandler.END
    order_id = int(context.args[0])
    with session_scope() as session:
        order = session.get(Order, order_id)
        job = session.scalar(
            select(AutomationJob).where(AutomationJob.order_id == order_id)
        )
        if not order:
            await update.message.reply_text("Pedido no encontrado.")
            return ConversationHandler.END
        if job and job.status == AutomationJob.STATUS_SUCCEEDED:
            await update.message.reply_text(
                "Ese trabajo ya terminó; no se modificó para evitar duplicados."
            )
            return ConversationHandler.END
        stock_id = order.automation_stock_id or (job.stock_item_id if job else None)
        if not stock_id:
            await update.message.reply_text("El pedido no tiene una cuenta reservada.")
            return ConversationHandler.END
        if job:
            session.delete(job)
            session.flush()
        order.status = Order.STATUS_APPROVED
        order.automation_stock_id = stock_id
        order.admin_note = "Esperando nueva configuración del cliente."
        telegram_id = order.user.telegram_id
    button = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "👤 Configurar mi perfil", callback_data=f"nfx:customer:{order_id}"
        )
    ]])
    await context.bot.send_message(
        telegram_id,
        f"✅ Configura nuevamente el perfil del pedido #{order_id}:",
        reply_markup=button,
    )
    await update.message.reply_text(
        f"✅ Pedido #{order_id} reiniciado. Se envió el botón al cliente."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nfx_order_id", None)
    context.user_data.pop("nfx_stock_id", None)
    context.user_data.pop("nfx_profile_name", None)
    await update.message.reply_text("Operación cancelada.", reply_markup=menu_markup())
    return ConversationHandler.END


def build_conversation() -> ConversationHandler:
    entries = [
        CommandHandler("netflix", show_menu),
        CommandHandler("netflixadmin", show_menu),
        CommandHandler("reconfigurarperfil", reconfigure_existing),
        CallbackQueryHandler(show_menu, pattern=r"^nfx:menu$"),
        CallbackQueryHandler(start_add, pattern=r"^nfx:add$"),
        CallbackQueryHandler(list_accounts, pattern=r"^nfx:list$"),
        CallbackQueryHandler(agent_status, pattern=r"^nfx:status$"),
        CallbackQueryHandler(start_test, pattern=r"^nfx:test$"),
        CallbackQueryHandler(select_order, pattern=r"^nfx:order:\d+$"),
        CallbackQueryHandler(select_stock, pattern=r"^nfx:stock:\d+:\d+$"),
        CallbackQueryHandler(start_customer_profile, pattern=r"^nfx:customer:\d+$"),
    ]
    return ConversationHandler(
        entry_points=entries,
        states={
            ADD_EMAIL: [
                CallbackQueryHandler(show_menu, pattern=r"^nfx:menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_email),
            ],
            TEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            TEST_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pin)],
            CUSTOMER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name)
            ],
            CUSTOMER_PIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, customer_pin)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True, per_user=True, per_chat=True,
    )
