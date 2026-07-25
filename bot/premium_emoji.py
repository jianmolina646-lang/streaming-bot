"""Formato seguro de mensajes con custom emoji de Telegram Premium."""
from __future__ import annotations

from html import escape
import re

from config import Settings


def premium_emoji(settings: Settings, kind: str, fallback: str) -> str:
    """Devuelve un custom emoji HTML o un emoji Unicode compatible."""
    custom_id = {
        "success": settings.premium_emoji_success_id,
        "key": settings.premium_emoji_key_id,
        "warning": settings.premium_emoji_warning_id,
        "star": settings.premium_emoji_star_id,
    }.get(kind, "")
    if not custom_id:
        return fallback
    return f'<tg-emoji emoji-id="{escape(custom_id, quote=True)}">{fallback}</tg-emoji>'


def delivery_message(
    settings: Settings,
    *,
    order_id: int,
    product: str,
    credentials: str,
    expires: str,
    amount: str | None = None,
) -> str:
    """Construye una entrega HTML sin interpretar credenciales como markup."""
    success = premium_emoji(settings, "success", "🎉")
    key = premium_emoji(settings, "key", "🔑")
    warning = premium_emoji(settings, "warning", "⚠️")
    amount_line = (
        f"\nImporte cobrado: <b>{escape(amount)}</b>"
        if amount
        else ""
    )
    return (
        f"{success} <b>¡Tu pedido #{order_id} ha sido entregado!</b>\n\n"
        f"Producto: {escape(product)}"
        f"{amount_line}\n"
        f"Vencimiento: <b>{escape(expires)}</b>\n\n"
        f"{key} <b>Tus credenciales</b>\n"
        f"<pre>{escape(credentials)}</pre>\n\n"
        f"{warning} No compartas estos datos. Si algo falla, usa "
        f"<code>/garantia {order_id}</code>."
    )


def review_request(settings: Settings) -> str:
    star = premium_emoji(settings, "star", "🌟")
    return f"{star} <b>¿Cómo te fue con esta compra?</b>\nTu opinión nos ayuda."


def without_custom_emoji(html_text: str) -> str:
    """Conserva el emoji Unicode si Telegram rechaza el custom emoji."""
    return re.sub(r'<tg-emoji emoji-id="[^"]+">(.+?)</tg-emoji>', r"\1", html_text)
