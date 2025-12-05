"""
TelegramNotifier: 用于通过 Telegram Bot API 发送消息.
现支持发送文本消息、图片和文件.
使用logger记录日志.
由于aiohttp 不支持代理环境变量，需要设置 trust_env=True

需要传参 token 和 chat_id, 或者通过环境变量 TELEGRAM_TOKEN 和 TELEGRAM_CHAT_ID 提供.
"""
import logging
import os
from typing import Any, Dict, Optional, Tuple

import aiohttp


class TelegramNotifier:
    logger = logging.getLogger(__name__)

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        # 验证必要参数否则抛出异常
        if not self.token or not self.chat_id:
            raise ValueError("TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID 未配置")

        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.timeout = aiohttp.ClientTimeout(total=20)

    async def _request(
        self,
        method: str,
        payload: Dict[str, Any],
        files: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        通用请求函数，用于封装所有 API 调用
        """
        url = f"{self.base_url}/{method}"
        try:
            # aiohttp 不支持代理环境变量，需要手动设置 trust_env=True
            async with aiohttp.ClientSession(trust_env=True, timeout=self.timeout) as session:
                if files:
                    form = aiohttp.FormData()
                    for k, v in payload.items():
                        form.add_field(k, str(v))
                    for k, v in files.items():
                        form.add_field(k, v, filename=getattr(v, "name", "file"))
                    async with session.post(url, data=form) as resp:
                        return await self._handle_response(resp)
                else:
                    async with session.post(url, json=payload) as resp:
                        return await self._handle_response(resp)
        except Exception as e:
            self.logger.error(f"[ERROR] Telegram 请求异常: {type(e).__name__}: {e}")
            return False, None

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> Tuple[bool, Optional[str]]:
        """
        处理 Telegram API 响应
        """
        try:
            if resp.status != 200:
                self.logger.error(f"[ERROR] Telegram 请求失败，状态码: {resp.status}")
                self.logger.debug(await resp.text())
                return False, None

            data = await resp.json()
            if not data.get("ok"):
                self.logger.error(f"[ERROR] Telegram 返回错误: {data}")
                return False, None

            msg_id = str(data.get("result", {}).get("message_id"))
            return True, msg_id
        except Exception as e:
            self.logger.error(f"[ERROR] 解析响应失败: {e}")
            return False, None

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> Tuple[bool, Optional[str]]:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        return await self._request("sendMessage", payload)

    async def send_photo(self, photo_path: str, caption: Optional[str] = None, parse_mode: str = "Markdown") -> Tuple[bool, Optional[str]]:
        payload = {"chat_id": self.chat_id, "caption": caption or "", "parse_mode": parse_mode}
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            return await self._request("sendPhoto", payload, files)

    async def send_document(self, file_path: str, caption: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        payload = {"chat_id": self.chat_id, "caption": caption or ""}
        with open(file_path, "rb") as f:
            files = {"document": f}
            return await self._request("sendDocument", payload, files)
