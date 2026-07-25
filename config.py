"""Carga de configuración desde variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: list[int] = field(default_factory=list)
    shop_name: str = "Mi Tienda Streaming"
    currency: str = "USD"
    payment_instructions: str = "Configura tus métodos de pago en .env"
    database_url: str = "sqlite:///shop.db"
    vip_threshold_1: float = 100.0
    vip_threshold_2: float = 300.0
    premium_emoji_success_id: str = ""
    premium_emoji_key_id: str = ""
    premium_emoji_warning_id: str = ""
    premium_emoji_star_id: str = ""


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN no está configurado. Copia .env.example a .env y rellena el token."
        )
    return Settings(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        shop_name=os.getenv("SHOP_NAME", "Mi Tienda Streaming"),
        currency=os.getenv("CURRENCY", "USD"),
        payment_instructions=os.getenv(
            "PAYMENT_INSTRUCTIONS",
            "Configura tus métodos de pago en .env",
        ).replace("\\n", "\n"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///shop.db"),
        vip_threshold_1=float(os.getenv("VIP_THRESHOLD_1", "100") or 100),
        vip_threshold_2=float(os.getenv("VIP_THRESHOLD_2", "300") or 300),
        premium_emoji_success_id=os.getenv("PREMIUM_EMOJI_SUCCESS_ID", "").strip(),
        premium_emoji_key_id=os.getenv("PREMIUM_EMOJI_KEY_ID", "").strip(),
        premium_emoji_warning_id=os.getenv("PREMIUM_EMOJI_WARNING_ID", "").strip(),
        premium_emoji_star_id=os.getenv("PREMIUM_EMOJI_STAR_ID", "").strip(),
    )
