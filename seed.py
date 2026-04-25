"""Script para precargar el catálogo con servicios y planes de ejemplo.

Ejecuta:  python -m scripts.seed
"""
from __future__ import annotations

from bot.db.database import init_db, session_scope
from bot.db.models import Plan, Service
from config import load_settings


SEED = [
    {
        "name": "Netflix",
        "emoji": "🎬",
        "description": "Suscripción a Netflix.",
        "plans": [
            {"name": "1 Mes — Perfil", "duration_days": 30, "price": 4.50},
            {"name": "1 Mes — Cuenta completa", "duration_days": 30, "price": 12.00},
        ],
    },
    {
        "name": "Amazon Prime Video",
        "emoji": "📦",
        "description": "Suscripción a Amazon Prime Video.",
        "plans": [
            {"name": "1 Mes", "duration_days": 30, "price": 3.50},
            {"name": "3 Meses", "duration_days": 90, "price": 9.00},
        ],
    },
    {
        "name": "Disney+",
        "emoji": "🏰",
        "description": "Suscripción a Disney+.",
        "plans": [
            {"name": "1 Mes — Perfil", "duration_days": 30, "price": 3.00},
        ],
    },
    {
        "name": "HBO Max",
        "emoji": "🎭",
        "description": "Suscripción a Max (antes HBO Max).",
        "plans": [
            {"name": "1 Mes — Perfil", "duration_days": 30, "price": 3.00},
        ],
    },
    {
        "name": "Spotify",
        "emoji": "🎵",
        "description": "Suscripción a Spotify Premium.",
        "plans": [
            {"name": "1 Mes — Premium individual", "duration_days": 30, "price": 4.00},
        ],
    },
]


def run() -> None:
    settings = load_settings()
    init_db(settings.database_url)
    with session_scope() as session:
        for entry in SEED:
            existing = session.query(Service).filter_by(name=entry["name"]).first()
            if existing:
                print(f"=  {entry['name']} ya existe, lo salto.")
                continue
            svc = Service(
                name=entry["name"],
                emoji=entry["emoji"],
                description=entry["description"],
            )
            session.add(svc)
            session.flush()
            for plan in entry["plans"]:
                session.add(
                    Plan(
                        service_id=svc.id,
                        name=plan["name"],
                        duration_days=plan["duration_days"],
                        price=plan["price"],
                    )
                )
            print(f"+  Creado {entry['name']} con {len(entry['plans'])} planes")
    print("Listo.")


if __name__ == "__main__":
    run()
