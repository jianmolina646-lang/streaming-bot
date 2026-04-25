"""Punto de entrada del bot."""
from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.db.database import init_db
from bot.handlers import admin as admin_h
from bot.handlers import catalog as catalog_h
from bot.handlers import orders as orders_h
from bot.handlers import start as start_h
from bot.jobs import mark_expired_and_notify, send_expiry_reminders
from config import load_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_application() -> Application:
    settings = load_settings()
    init_db(settings.database_url)
    app = Application.builder().token(settings.bot_token).build()
    app.bot_data["settings"] = settings

    # Comandos básicos.
    app.add_handler(CommandHandler("start", start_h.cmd_start))
    app.add_handler(CommandHandler("help", start_h.cmd_help))
    app.add_handler(CommandHandler("ayuda", start_h.cmd_help))
    app.add_handler(CommandHandler("soporte", start_h.cmd_support))
    app.add_handler(CommandHandler("catalogo", catalog_h.show_catalog))
    app.add_handler(CommandHandler("pedidos", orders_h.show_my_orders))
    app.add_handler(CommandHandler("faq", start_h.cmd_faq))
    app.add_handler(CommandHandler("saldo", start_h.cmd_saldo))
    app.add_handler(CommandHandler("referidos", start_h.cmd_referrals))
    app.add_handler(CommandHandler("cupon", orders_h.cmd_apply_coupon))
    app.add_handler(CommandHandler("garantia", orders_h.cmd_warranty))

    # Comandos admin.
    app.add_handler(CommandHandler("admin", admin_h.cmd_admin))
    app.add_handler(CommandHandler("addservice", admin_h.cmd_add_service))
    app.add_handler(CommandHandler("listservices", admin_h.cmd_list_services))
    app.add_handler(CommandHandler("editservice", admin_h.cmd_edit_service))
    app.add_handler(CommandHandler("delservice", admin_h.cmd_del_service))
    app.add_handler(CommandHandler("addplan", admin_h.cmd_add_plan))
    app.add_handler(CommandHandler("listplans", admin_h.cmd_list_plans))
    app.add_handler(CommandHandler("editprice", admin_h.cmd_edit_price))
    app.add_handler(CommandHandler("editplan", admin_h.cmd_edit_plan))
    app.add_handler(CommandHandler("delplan", admin_h.cmd_del_plan))
    app.add_handler(CommandHandler("enableplan", admin_h.cmd_toggle_plan))
    app.add_handler(CommandHandler("disableplan", admin_h.cmd_toggle_plan))
    app.add_handler(CommandHandler("orders", admin_h.cmd_orders))
    app.add_handler(CommandHandler("order", admin_h.cmd_order))
    app.add_handler(CommandHandler("expiring", admin_h.cmd_expiring))
    app.add_handler(CommandHandler("expired", admin_h.cmd_expired))
    app.add_handler(CommandHandler("markcut", admin_h.cmd_mark_cut))
    app.add_handler(CommandHandler("cutall", admin_h.cmd_cut_all))
    app.add_handler(CommandHandler("addbalance", admin_h.cmd_add_balance))
    app.add_handler(CommandHandler("setbalance", admin_h.cmd_set_balance))
    app.add_handler(CommandHandler("balance", admin_h.cmd_balance))
    app.add_handler(CommandHandler("topbalances", admin_h.cmd_top_balances))
    app.add_handler(CommandHandler("wallethistory", admin_h.cmd_wallet_history))
    app.add_handler(CommandHandler("searchuser", admin_h.cmd_search_user))
    app.add_handler(CommandHandler("orderhistory", admin_h.cmd_order_history))
    app.add_handler(CommandHandler("reply", admin_h.cmd_reply))
    app.add_handler(CommandHandler("addfaq", admin_h.cmd_add_faq))
    app.add_handler(CommandHandler("listfaq", admin_h.cmd_list_faq))
    app.add_handler(CommandHandler("delfaq", admin_h.cmd_del_faq))
    app.add_handler(CommandHandler("stats", admin_h.cmd_stats))
    app.add_handler(CommandHandler("broadcast", admin_h.cmd_broadcast))

    # --- v4: Cupones / refund / replace / vip / warranty / reviews / etc ---
    app.add_handler(CommandHandler("addcoupon", admin_h.cmd_add_coupon))
    app.add_handler(CommandHandler("listcoupons", admin_h.cmd_list_coupons))
    app.add_handler(CommandHandler("delcoupon", admin_h.cmd_del_coupon))
    app.add_handler(CommandHandler("refund", admin_h.cmd_refund))
    app.add_handler(CommandHandler("replace", admin_h.cmd_replace))
    app.add_handler(CommandHandler("blockuser", admin_h.cmd_block_user))
    app.add_handler(CommandHandler("unblock", admin_h.cmd_unblock_user))
    app.add_handler(CommandHandler("note", admin_h.cmd_note))
    app.add_handler(CommandHandler("vip", admin_h.cmd_vip))
    app.add_handler(CommandHandler("tickets", admin_h.cmd_tickets))
    app.add_handler(CommandHandler("resolveticket", admin_h.cmd_resolve_ticket))
    app.add_handler(CommandHandler("reviews", admin_h.cmd_reviews))
    app.add_handler(CommandHandler("stocklist", admin_h.cmd_stock_list))
    app.add_handler(CommandHandler("delstock", admin_h.cmd_del_stock))
    app.add_handler(CommandHandler("broadcast_service", admin_h.cmd_broadcast_service))
    app.add_handler(CommandHandler("promo", admin_h.cmd_promo))
    app.add_handler(CommandHandler("topservices", admin_h.cmd_top_services))
    app.add_handler(CommandHandler("topclientes", admin_h.cmd_top_clients))
    app.add_handler(CommandHandler("export", admin_h.cmd_export))
    app.add_handler(CommandHandler("maintenance", admin_h.cmd_maintenance))
    app.add_handler(CommandHandler("setpayment", admin_h.cmd_set_payment))
    app.add_handler(CommandHandler("setshop", admin_h.cmd_set_shop))

    # Conversación para añadir stock (incluye /bulkstock).
    app.add_handler(admin_h.build_addstock_conversation())

    # Callbacks inline.
    app.add_handler(CallbackQueryHandler(catalog_h.show_service, pattern=r"^svc:\d+$"))
    app.add_handler(CallbackQueryHandler(catalog_h.show_plan, pattern=r"^plan:\d+$"))
    app.add_handler(CallbackQueryHandler(orders_h.start_purchase, pattern=r"^buy:\d+$"))
    app.add_handler(CallbackQueryHandler(orders_h.cb_pay_manual, pattern=r"^pay:manual:\d+$"))
    app.add_handler(CallbackQueryHandler(orders_h.cb_pay_wallet, pattern=r"^pay:wallet:\d+$"))
    app.add_handler(CallbackQueryHandler(orders_h.cancel_order, pattern=r"^order:cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(catalog_h.back_to_services, pattern=r"^back:services$"))
    app.add_handler(CallbackQueryHandler(catalog_h.show_service, pattern=r"^back:plan:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_h.cb_admin_action, pattern=r"^adm:(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(catalog_h.cb_waitlist, pattern=r"^wait:\d+$"))
    app.add_handler(CallbackQueryHandler(orders_h.cb_review, pattern=r"^review:\d+:[0-5]$"))

    # Comprobantes de pago: fotos o documentos.
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, orders_h.receive_payment_proof)
    )

    # Botones del teclado de respuesta principal.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start_h.menu_router))

    return app


def main() -> None:
    setup_logging()
    app = build_application()
    # Recordatorios de vencimiento: se ejecuta cada 6 horas y revisa pedidos
    # cuyo expires_at cae en ~3 días, para enviar al cliente un aviso de renovación.
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            send_expiry_reminders,
            interval=timedelta(hours=6),
            first=timedelta(seconds=30),
            name="expiry-reminders",
        )
        # Marca pedidos vencidos como expired y avisa cliente + admin para corte.
        app.job_queue.run_repeating(
            mark_expired_and_notify,
            interval=timedelta(hours=1),
            first=timedelta(seconds=60),
            name="expired-cutter",
        )
    logging.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
