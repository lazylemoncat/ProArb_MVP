"""
TelegramNotifier: 用于通过 Telegram Bot API 发送消息.
现支持发送文本消息、图片和文件.
使用logger记录日志.
由于aiohttp 不支持代理环境变量，需要设置 trust_env=True

需要传参 token 和 chat_id, 或者通过环境变量 TELEGRAM_TOKEN 和 TELEGRAM_CHAT_ID 提供.
"""
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


class TelegramNotifier:
    logger = logging.getLogger(__name__)

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):

        self.token = token
        self.chat_id = chat_id
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
        """
        Send a photo to Telegram.

        Args:
            photo_path: Path to the photo file
            caption: Optional caption for the photo
            parse_mode: Parse mode for caption (default: Markdown)

        Returns:
            Tuple of (success, message_id)
        """
        payload = {"chat_id": self.chat_id, "caption": caption or "", "parse_mode": parse_mode}
        # Read file content into memory to avoid file handle lifecycle issues
        with open(photo_path, "rb") as f:
            file_content = f.read()
            file_name = photo_path.split("/")[-1]

        # Create a file-like object from bytes
        file_obj = io.BytesIO(file_content)
        file_obj.name = file_name

        files = {"photo": file_obj}
        return await self._request("sendPhoto", payload, files)

    async def send_document(self, file_path: str, caption: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Send a document/file to Telegram.

        Args:
            file_path: Path to the file to send
            caption: Optional caption for the document

        Returns:
            Tuple of (success, message_id)
        """
        payload = {"chat_id": self.chat_id, "caption": caption or ""}
        # Read file content into memory to avoid file handle lifecycle issues
        with open(file_path, "rb") as f:
            file_content = f.read()
            file_name = file_path.split("/")[-1]

        # Create a file-like object from bytes
        file_obj = io.BytesIO(file_content)
        file_obj.name = file_name

        files = {"document": file_obj}
        return await self._request("sendDocument", payload, files)

    async def get_updates(
        self,
        offset: int = 0,
        limit: int = 100,
        timeout: int = 30,
        allowed_updates: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        使用 getUpdates 长轮询获取新消息。

        用于接收用户发送给机器人的消息和命令。

        Args:
            offset: 返回的第一个更新的 ID，用于确认已处理的更新
            limit: 返回更新数量限制，1-100，默认 100
            timeout: 长轮询超时秒数，0 表示短轮询
            allowed_updates: 指定接收的更新类型，如 ["message"]

        Returns:
            Update 对象列表，获取失败时返回空列表

        Example:
            updates = await notifier.get_updates(offset=last_update_id + 1, timeout=30)
            for update in updates:
                message = update.get("message", {})
                text = message.get("text", "")
                # 处理消息...
        """
        url = f"{self.base_url}/getUpdates"

        params = {
            "offset": offset,
            "limit": limit,
            "timeout": timeout,
        }
        if allowed_updates:
            params["allowed_updates"] = allowed_updates

        try:
            # 使用较长的超时时间（timeout + 10 秒缓冲）
            long_timeout = aiohttp.ClientTimeout(total=timeout + 10)
            async with aiohttp.ClientSession(trust_env=True, timeout=long_timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        self.logger.error(f"[ERROR] getUpdates 失败，状态码: {resp.status}")
                        return []

                    data = await resp.json()
                    if not data.get("ok"):
                        self.logger.error(f"[ERROR] getUpdates 返回错误: {data}")
                        return []

                    return data.get("result", [])

        except Exception as e:
            self.logger.error(f"[ERROR] getUpdates 异常: {type(e).__name__}: {e}")
            return []

    async def reply_to_message(
        self,
        text: str,
        reply_to_message_id: int,
        parse_mode: str = "Markdown"
    ) -> Tuple[bool, Optional[str]]:
        """
        回复指定消息。

        Args:
            text: 回复文本
            reply_to_message_id: 要回复的消息 ID
            parse_mode: 格式化模式

        Returns:
            Tuple of (success, message_id)
        """
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_to_message_id": reply_to_message_id,
        }
        return await self._request("sendMessage", payload)
