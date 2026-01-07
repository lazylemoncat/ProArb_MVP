import logging
from typing import Optional, Tuple

from .telegramNotifier import TelegramNotifier

logger = logging.getLogger(__name__)


class TG_bot:
    def __init__(self, name: str, token: str, chat_id: str):
        self.name = name
        self.notifier = TelegramNotifier(token=token, chat_id=chat_id)

    async def publish(self, msg: str) -> Tuple[bool, Optional[str]]:
        """
        Send a text message to Telegram.

        Args:
            msg: The message text to send

        Returns:
            Tuple of (success, message_id)
        """
        try:
            success, msg_id = await self.notifier.send_message(text=msg, parse_mode="")
            return success, msg_id
        except Exception as e:
            logger.error(f"Failed to publish message: {e}", exc_info=True)
            raise

    async def send_document(
        self, file_path: str, caption: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Send a document/file to Telegram.

        Args:
            file_path: Path to the file to send
            caption: Optional caption for the document

        Returns:
            Tuple of (success, message_id)
        """
        try:
            success, msg_id = await self.notifier.send_document(
                file_path=file_path, caption=caption
            )
            if not success:
                logger.warning(f"Failed to send document: {file_path}")
            return success, msg_id
        except Exception as e:
            logger.error(f"Failed to send document {file_path}: {e}", exc_info=True)
            raise
