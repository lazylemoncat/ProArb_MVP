from dataclasses import dataclass

import dotenv

from .get_value import get_value_from_env

dotenv.load_dotenv()

@dataclass
class Env_config:
    deribit_client_secret: str
    deribit_user_id: str
    deribit_client_id: str

    ENABLE_LIVE_TRADING: bool

    polymarket_secret: str

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

def load_env_config():
    return Env_config(
        deribit_client_secret=str(get_value_from_env("deribit_client_secret")),
        deribit_user_id=str(get_value_from_env("deribit_user_id")),
        deribit_client_id=str(get_value_from_env("deribit_client_id")),
        ENABLE_LIVE_TRADING=bool(get_value_from_env("ENABLE_LIVE_TRADING")),
        polymarket_secret=str(get_value_from_env("polymarket_secret")),
        TELEGRAM_ENABLED=bool(get_value_from_env("TELEGRAM_ENABLED")),
        TELEGRAM_ALART_ENABLED=bool(get_value_from_env("TELEGRAM_ALART_ENABLED")),
        TELEGRAM_TRADING_ENABLED=bool(get_value_from_env("TELEGRAM_TRADING_ENABLED")),
        TELEGRAM_BOT_TOKEN_ALERT=str(get_value_from_env("TELEGRAM_BOT_TOKEN_ALERT")),
        TELEGRAM_BOT_TOKEN_TRADING=str(get_value_from_env("TELEGRAM_BOT_TOKEN_TRADING")),
        TELEGRAM_CHAT_ID=str(get_value_from_env("TELEGRAM_CHAT_ID")),
        MAX_RETRIES=int(get_value_from_env("MAX_RETRIES")),
        RETRY_DELAY_SECONDS=int(get_value_from_env("RETRY_DELAY_SECONDS")),
        RETRY_BACKOFF=int(get_value_from_env("RETRY_BACKOFF")),
        TELEGRAM_MAX_MSG_PER_SEC=int(get_value_from_env("TELEGRAM_MAX_MSG_PER_SEC"))
    )