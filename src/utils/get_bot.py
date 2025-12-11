from typing import Literal

from .dataloader.dataloader import Env_config
from ..telegram.TG_bot import TG_bot

def get_bot(name: Literal["alert", "trading"], env_config: Env_config):
    chat_id = str(env_config.TELEGRAM_CHAT_ID)
    if name == "alert":
        alert_token = str(env_config.TELEGRAM_BOT_TOKEN_ALERT)
        return TG_bot(name=name, token=alert_token, chat_id=chat_id)
    elif name == "trading":
        trading_token = str(env_config.TELEGRAM_BOT_TOKEN_TRADING)
        return TG_bot(name=name, token=trading_token, chat_id=chat_id)
    else:
        assert False