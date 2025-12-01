from dataclasses import dataclass
import os
import dotenv

dotenv.load_dotenv()

@dataclass
class Env_config:
    deribit_client_secret: str
    deribit_user_id: str
    deribit_client_id: str

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
        deribit_client_secret=os.getenv("deribit_client_secret"),
        deribit_user_id=os.getenv("deribit_user_id"),
        deribit_client_id=os.getenv("deribit_client_id"),
        polymarket_secret=os.getenv("polymarket_secret"),
        TELEGRAM_ENABLED=os.getenv("TELEGRAM_ENABLED"),
        TELEGRAM_ALART_ENABLED=os.getenv("TELEGRAM_ALART_ENABLED"),
        TELEGRAM_TRADING_ENABLED=os.getenv("TELEGRAM_TRADING_ENABLED"),
        TELEGRAM_BOT_TOKEN_ALERT=os.getenv("TELEGRAM_BOT_TOKEN_ALERT"),
        TELEGRAM_BOT_TOKEN_TRADING=os.getenv("TELEGRAM_BOT_TOKEN_TRADING"),
        TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID"),
        MAX_RETRIES=os.getenv("MAX_RETRIES"),
        RETRY_DELAY_SECONDS=os.getenv("RETRY_DELAY_SECONDS"),
        RETRY_BACKOFF=os.getenv("RETRY_BACKOFF"),
        TELEGRAM_MAX_MSG_PER_SEC=os.getenv("TELEGRAM_MAX_MSG_PER_SEC")
    )