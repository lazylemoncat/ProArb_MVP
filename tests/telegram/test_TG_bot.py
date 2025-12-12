import pytest

from src.telegram.TG_bot import TG_bot
from src.utils.dataloader import load_all_configs

@pytest.mark.asyncio
async def test_publish():
    env_config, _, _ = load_all_configs(dotenv_path="dev.env")
    alert_token = str(env_config.TELEGRAM_BOT_TOKEN_ALERT)
    chat_id = str(env_config.TELEGRAM_CHAT_ID)
    alert_bot = TG_bot(
        name="alert", 
        token=alert_token,
        chat_id=chat_id
    )
    assert (await alert_bot.publish("test"))[1]