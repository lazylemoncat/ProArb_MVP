from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

import aiohttp


logger = logging.getLogger(__name__)


class TelegramBotClient:
    """Thin Telegram Bot API client for sendMessage."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # trust_env=True: respect HTTP(S)_PROXY env vars (common on servers)
            self._session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_text(self, text: str, parse_mode: Optional[str] = None, disable_web_page_preview: bool = True) -> Tuple[bool, Optional[str]]:
        session = await self._get_session()
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        url = f"{self.base_url}/sendMessage"
        try:
            async with session.post(url, json=payload) as resp:
                body = await resp.text()
                if resp.status != 200:
                    return False, f"HTTP {resp.status}: {body}"
                return True, None
        except asyncio.TimeoutError:
            return False, "timeout"
        except Exception as exc:
            return False, str(exc)
