from dataclasses import dataclass

import dotenv
import os

from .get_value import get_value_from_env

dotenv.load_dotenv()


@dataclass
class Env_config:
    deribit_client_secret: str
    deribit_user_id: str
    deribit_client_id: str

    DERIBIT_ENV_PREFIX: str

    ENABLE_LIVE_TRADING: bool

    polymarket_secret: str
    POLYMARKET_PROXY_ADDRESS: str

    TELEGRAM_ENABLED: bool
    TELEGRAM_ALART_ENABLED: bool
    TELEGRAM_TRADING_ENABLED: bool

    TELEGRAM_BOT_TOKEN_ALERT: str
    TELEGRAM_BOT_TOKEN_TRADING: str
    TELEGRAM_CHAT_ID: str

    MAX_RETRIES: int
    RETRY_DELAY_SECONDS: int
    RETRY_BACKOFF: int
    TELEGRAM_MAX_MSG_PER_SEC: int
    TELEGRAM_QUEUE_MAXSIZE: int
    TELEGRAM_DEADLETTER_PATH: str

    EV_REFRESH_SECONDS: float
    LOG_LEVEL: str


def _get_optional_env(key: str, default: str | float | bool | None = None):
    value = os.getenv(key)
    if value is None:
        return default

    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        return float(value) if "." in value or lowered.isdigit() else value
    except ValueError:
        return value


def load_env_config():
    return Env_config(
        deribit_client_secret=str(get_value_from_env("deribit_client_secret")),
        deribit_user_id=str(get_value_from_env("deribit_user_id")),
        deribit_client_id=str(get_value_from_env("deribit_client_id")),
        DERIBIT_ENV_PREFIX=str(_get_optional_env("DERIBIT_ENV_PREFIX", "")),
        ENABLE_LIVE_TRADING=bool(get_value_from_env("ENABLE_LIVE_TRADING")),
        polymarket_secret=str(get_value_from_env("polymarket_secret")),
        POLYMARKET_PROXY_ADDRESS=str(
            _get_optional_env(
                "POLYMARKET_PROXY_ADDRESS",
                "0x1bD027BCA18bCe3dC541850FB42b789439b36B6D",
            )
        ),
        TELEGRAM_ENABLED=bool(get_value_from_env("TELEGRAM_ENABLED")),
        TELEGRAM_ALART_ENABLED=bool(get_value_from_env("TELEGRAM_ALART_ENABLED")),
        TELEGRAM_TRADING_ENABLED=bool(get_value_from_env("TELEGRAM_TRADING_ENABLED")),
        TELEGRAM_BOT_TOKEN_ALERT=str(get_value_from_env("TELEGRAM_BOT_TOKEN_ALERT")),
        TELEGRAM_BOT_TOKEN_TRADING=str(get_value_from_env("TELEGRAM_BOT_TOKEN_TRADING")),
        TELEGRAM_CHAT_ID=str(get_value_from_env("TELEGRAM_CHAT_ID")),
        MAX_RETRIES=int(get_value_from_env("MAX_RETRIES")),
        RETRY_DELAY_SECONDS=int(get_value_from_env("RETRY_DELAY_SECONDS")),
        RETRY_BACKOFF=int(get_value_from_env("RETRY_BACKOFF")),
        TELEGRAM_MAX_MSG_PER_SEC=int(get_value_from_env("TELEGRAM_MAX_MSG_PER_SEC")),
        TELEGRAM_QUEUE_MAXSIZE=int(_get_optional_env("TELEGRAM_QUEUE_MAXSIZE", 1000)),
        TELEGRAM_DEADLETTER_PATH=str(_get_optional_env("TELEGRAM_DEADLETTER_PATH", "data/telegram_deadletter.jsonl")),
        EV_REFRESH_SECONDS=float(_get_optional_env("EV_REFRESH_SECONDS", 10.0)),
        LOG_LEVEL=str(_get_optional_env("LOG_LEVEL", "INFO")),
    )
