from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_bool_first(names: list[str], default: bool) -> bool:
    """
    多个 env 名称按优先级读取，找到第一个存在的就用它解析 bool。
    例如兼容拼写错误：TELEGRAM_ALART_ENABLED / TELEGRAM_ALERT_ENABLED
    """
    for n in names:
        if os.getenv(n) is not None:
            return _env_bool(n, default=default)
    return default


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


def _env_chat_id() -> Optional[str]:
    return os.getenv("TELEGRAM_CHAT_ID") or (
        (os.getenv("TELEGRAM_CHAT_IDS", "").split(",")[0].strip() or None)
        if os.getenv("TELEGRAM_CHAT_IDS")
        else None
    )


@dataclass(frozen=True)
class TelegramSettings:
    """Telegram bot settings (two bots, one chat)."""

    # 总开关（仍然保留）
    enabled: bool = field(default_factory=lambda: _env_bool("TELEGRAM_ENABLED", default=False))

    # 新增：分别控制 Bot1 / Bot2 的开关
    # 兼容你新增的 TELEGRAM_ALART_ENABLED（拼写）以及标准写法 TELEGRAM_ALERT_ENABLED
    alert_enabled: bool = field(
        default_factory=lambda: _env_bool_first(["TELEGRAM_ALART_ENABLED", "TELEGRAM_ALERT_ENABLED"], default=True)
    )
    trading_enabled: bool = field(default_factory=lambda: _env_bool("TELEGRAM_TRADING_ENABLED", default=True))

    # Bot tokens
    bot_token_alert: Optional[str] = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN_ALERT") or os.getenv("TELEGRAM_BOT_TOKEN")
    )
    bot_token_trading: Optional[str] = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN_TRADING") or os.getenv("TELEGRAM_BOT_TOKEN")
    )

    # Chat id(s)
    chat_id: Optional[str] = field(default_factory=_env_chat_id)

    # Retry policy
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    retry_delay_seconds: float = field(default_factory=lambda: _env_float("RETRY_DELAY_SECONDS", 1.0))
    retry_backoff: float = field(default_factory=lambda: _env_float("RETRY_BACKOFF", 2.0))

    # Rate limiting
    max_messages_per_second: float = field(default_factory=lambda: _env_float("TELEGRAM_MAX_MSG_PER_SEC", 5.0))

    # Queue settings
    queue_maxsize: int = field(default_factory=lambda: _env_int("TELEGRAM_QUEUE_MAXSIZE", 1000))

    # Dead-letter log
    deadletter_path: str = field(default_factory=lambda: os.getenv("TELEGRAM_DEADLETTER_PATH", "data/telegram_deadletter.jsonl"))
