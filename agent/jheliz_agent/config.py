from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


@dataclass(frozen=True)
class AgentConfig:
    api_url: str
    token: str
    name: str
    dry_run: bool
    poll_seconds: int
    browser: str
    headless: bool

    @classmethod
    def from_env(cls) -> "AgentConfig":
        config = cls(
            api_url=os.getenv("JHELIZ_AGENT_API_URL", "").strip().rstrip("/"),
            token=os.getenv("JHELIZ_AGENT_TOKEN", "").strip(),
            name=os.getenv("JHELIZ_AGENT_NAME", "windows-agent").strip(),
            dry_run=_boolean("JHELIZ_AGENT_DRY_RUN", True),
            poll_seconds=max(2, int(os.getenv("JHELIZ_AGENT_POLL_SECONDS", "5"))),
            browser=os.getenv("JHELIZ_AGENT_BROWSER", "chromium").strip().lower(),
            headless=_boolean("JHELIZ_AGENT_HEADLESS", False),
        )
        if not config.api_url.startswith("https://"):
            raise ValueError("JHELIZ_AGENT_API_URL debe utilizar HTTPS")
        if len(config.token) < 32:
            raise ValueError("JHELIZ_AGENT_TOKEN no está configurado o es demasiado corto")
        if config.browser not in {"chromium", "chrome", "msedge"}:
            raise ValueError("JHELIZ_AGENT_BROWSER debe ser chromium, chrome o msedge")
        return config
