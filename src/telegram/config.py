from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..utils.dataloader import load_all_configs


_CONFIG_CACHE: dict[str, Any] | None = None


def _get_config() -> dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_all_configs()
    return _CONFIG_CACHE


def _cfg_bool(key: str, default: bool = False) -> bool:
    val = _get_config().get(key, default)
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y", "on")
    try:
        return bool(val)
    except Exception:
        return default


def _cfg_int(key: str, default: int) -> int:
    val = _get_config().get(key, default)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _cfg_float(key: str, default: float) -> float:
    val = _get_config().get(key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _cfg_first(keys: list[str], default: Optional[str] = None) -> Optional[str]:
    cfg = _get_config()
    for key in keys:
        val = cfg.get(key)
        if val not in (None, ""):
            return str(val)
    return default


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram bot settings (two bots, one chat)."""

    enabled: bool = field(default_factory=lambda: _cfg_bool("TELEGRAM_ENABLED", default=False))

    alert_enabled: bool = field(
        default_factory=lambda: _cfg_bool("TELEGRAM_ALART_ENABLED", default=_cfg_bool("TELEGRAM_ALERT_ENABLED", True))
    )
    trading_enabled: bool = field(default_factory=lambda: _cfg_bool("TELEGRAM_TRADING_ENABLED", default=True))

    bot_token_alert: Optional[str] = field(
        default_factory=lambda: _cfg_first(["TELEGRAM_BOT_TOKEN_ALERT", "TELEGRAM_BOT_TOKEN"])
    )
    bot_token_trading: Optional[str] = field(
        default_factory=lambda: _cfg_first(["TELEGRAM_BOT_TOKEN_TRADING", "TELEGRAM_BOT_TOKEN"])
    )

    chat_id: Optional[str] = field(default_factory=lambda: _cfg_first(["TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_IDS"], None))

    max_retries: int = field(default_factory=lambda: _cfg_int("MAX_RETRIES", 3))
    retry_delay_seconds: float = field(default_factory=lambda: _cfg_float("RETRY_DELAY_SECONDS", 1.0))
    retry_backoff: float = field(default_factory=lambda: _cfg_float("RETRY_BACKOFF", 2.0))

    max_messages_per_second: float = field(default_factory=lambda: _cfg_float("TELEGRAM_MAX_MSG_PER_SEC", 5.0))

    queue_maxsize: int = field(default_factory=lambda: _cfg_int("TELEGRAM_QUEUE_MAXSIZE", 1000))

    deadletter_path: str = field(
        default_factory=lambda: _cfg_first(["TELEGRAM_DEADLETTER_PATH"], "data/telegram_deadletter.jsonl")
    )
