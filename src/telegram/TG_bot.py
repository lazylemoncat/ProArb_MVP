from .telegramNotifier import TelegramNotifier


class TG_bot:
    def __init__(self, name: str, token: str, chat_id: str):
        self.name = name
        self.notifier = TelegramNotifier(token=token, chat_id=chat_id)

    async def publish(self, msg: str):
        try:
            success, msg_id = await self.notifier.send_message(text=msg)
            return success, msg_id
        except:
            raise

