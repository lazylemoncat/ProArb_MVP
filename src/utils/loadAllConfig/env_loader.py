import os
from dataclasses import dataclass
from typing import Mapping

import dotenv

from ._get_value import get_value_from_dict, parse_bool


@dataclass(frozen=True)
class Env_config:
    DERIBIT_CLIENT_SECRET: str
    DERIBIT_USER_ID: str
    DERIBIT_CLIENT_ID: str

    POLYMARKET_SECRET: str
    POLYMARKET_PROXY_ADDRESS: str

    SIGNER_URL: str
    SIGNING_TOKEN: str

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

def parse_env_config(env: Mapping[str, str]) -> Env_config:
    return Env_config(
        DERIBIT_CLIENT_SECRET=str(get_value_from_dict(env, "deribit_client_secret")),
        DERIBIT_USER_ID=str(get_value_from_dict(env, "deribit_user_id")),
        DERIBIT_CLIENT_ID=str(get_value_from_dict(env, "deribit_client_id")),

        POLYMARKET_SECRET=str(get_value_from_dict(env, "polymarket_secret")),
        POLYMARKET_PROXY_ADDRESS=str(get_value_from_dict(env, "POLYMARKET_PROXY_ADDRESS")),

        SIGNER_URL=str(get_value_from_dict(env, "SIGNER_URL")),
        SIGNING_TOKEN=str(get_value_from_dict(env, "SIGNING_TOKEN")),

        TELEGRAM_ENABLED=parse_bool(get_value_from_dict(env, "TELEGRAM_ENABLED")),
        TELEGRAM_ALART_ENABLED=parse_bool(get_value_from_dict(env, "TELEGRAM_ALART_ENABLED")),
        TELEGRAM_TRADING_ENABLED=parse_bool(get_value_from_dict(env, "TELEGRAM_TRADING_ENABLED")),

        TELEGRAM_BOT_TOKEN_ALERT=str(get_value_from_dict(env, "TELEGRAM_BOT_TOKEN_ALERT")),
        TELEGRAM_BOT_TOKEN_TRADING=str(get_value_from_dict(env, "TELEGRAM_BOT_TOKEN_TRADING")),
        TELEGRAM_CHAT_ID=str(get_value_from_dict(env, "TELEGRAM_CHAT_ID")),

        MAX_RETRIES=int(get_value_from_dict(env, "MAX_RETRIES")),
        RETRY_DELAY_SECONDS=int(get_value_from_dict(env, "RETRY_DELAY_SECONDS")),
        RETRY_BACKOFF=int(get_value_from_dict(env, "RETRY_BACKOFF")),
        TELEGRAM_MAX_MSG_PER_SEC=int(get_value_from_dict(env, "TELEGRAM_MAX_MSG_PER_SEC")),
    )

def load_env_config(dotenv_path: str = ".env"):
    dotenv.load_dotenv(dotenv_path)
    return parse_env_config(os.environ)