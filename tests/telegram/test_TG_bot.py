from src.telegram.telegramNotifier import TelegramNotifier
from dotenv import load_dotenv
import os
import pytest

@pytest.mark.asyncio
async def test_tele():
    load_dotenv("dev.env")
    tn = TelegramNotifier(
        os.getenv("TELEGRAM_BOT_TOKEN_ALERT"),
        os.getenv("TELEGRAM_CHAT_ID")
    )
    await tn.send_document("data//raw_results.csv")