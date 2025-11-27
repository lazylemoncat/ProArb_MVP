from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram bot settings (two bots, one chat).

    Env priority:
      - TELEGRAM_BOT_TOKEN_ALERT / TELEGRAM_BOT_TOKEN_TRADING (preferred)
      - fallback to TELEGRAM_BOT_TOKEN (legacy)
    Chat:
      - TELEGRAM_CHAT_ID (preferred)
      - fallback to TELEGRAM_CHAT_IDS first item (legacy)
    """

    enabled: bool = _env_bool("TELEGRAM_ENABLED", default=False)

    # Bot tokens
    bot_token_alert: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN_ALERT") or os.getenv("TELEGRAM_BOT_TOKEN")
    bot_token_trading: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN_TRADING") or os.getenv("TELEGRAM_BOT_TOKEN")

    # Chat id(s)
    chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID") or (
        (os.getenv("TELEGRAM_CHAT_IDS", "").split(",")[0].strip() or None) if os.getenv("TELEGRAM_CHAT_IDS") else None
    )

    # Retry policy
    max_retries: int = _env_int("MAX_RETRIES", 3)
    retry_delay_seconds: float = _env_float("RETRY_DELAY_SECONDS", 1.0)
    retry_backoff: float = _env_float("RETRY_BACKOFF", 2.0)

    # Rate limiting (Telegram official: ~30 msg/s; default to 5 msg/s per bot)
    max_messages_per_second: float = _env_float("TELEGRAM_MAX_MSG_PER_SEC", 5.0)

    # Queue settings
    queue_maxsize: int = _env_int("TELEGRAM_QUEUE_MAXSIZE", 1000)

    # Dead-letter log
    deadletter_path: str = os.getenv("TELEGRAM_DEADLETTER_PATH", "data/telegram_deadletter.jsonl")
