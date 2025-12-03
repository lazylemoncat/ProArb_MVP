from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import TypeAdapter, ValidationError

from .config import TelegramSettings
from .formatter_v2 import format_message
from .models import OpportunityMessage, TradeMessage, ErrorMessage, RecoveryMessage, TelegramMessage
from .notifier import TelegramBotClient
from .rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

_TELEGRAM_MESSAGE_ADAPTER = TypeAdapter(TelegramMessage)


@dataclass
class _Bots:
    alert: Optional[TelegramBotClient]
    trading: Optional[TelegramBotClient]


class TelegramWorker:
    """Async queue worker that routes JSON messages to Telegram bots."""

    def __init__(self, settings: Optional[TelegramSettings] = None):
        self.settings = settings or TelegramSettings()

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[str]] = None
        self._task: Optional[asyncio.Task] = None
        self._bots: Optional[_Bots] = None
        self._lim_alert: Optional[AsyncRateLimiter] = None
        self._lim_trading: Optional[AsyncRateLimiter] = None

        self._started = False

    def start(self) -> None:
        if self._started:
            return

        if not self.settings.enabled:
            logger.info("telegram disabled (TELEGRAM_ENABLED=false)")
            self._started = True
            return

        if not self.settings.alert_enabled and not self.settings.trading_enabled:
            logger.info("telegram enabled but both bots disabled (alert_enabled=false, trading_enabled=false)")
            self._started = True
            return

        if not self.settings.chat_id:
            logger.warning("telegram enabled but missing chat_id")
            self._started = True
            return

        if self.settings.alert_enabled and not self.settings.bot_token_alert:
            logger.warning("telegram alert enabled but missing TELEGRAM_BOT_TOKEN_ALERT")
            self._started = True
            return

        if self.settings.trading_enabled and not self.settings.bot_token_trading:
            logger.warning("telegram trading enabled but missing TELEGRAM_BOT_TOKEN_TRADING")
            self._started = True
            return

        try:
            loop = asyncio.get_running_loop()
            self._start_in_loop(loop)
        except RuntimeError:
            self._start_in_thread()

        self._started = True

    def _start_in_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """在事件循环中启动 Telegram worker"""
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=self.settings.queue_maxsize)

        alert_bot = (
            TelegramBotClient(self.settings.bot_token_alert, self.settings.chat_id)
            if self.settings.alert_enabled and self.settings.bot_token_alert
            else None
        )
        trading_bot = (
            TelegramBotClient(self.settings.bot_token_trading, self.settings.chat_id)
            if self.settings.trading_enabled and self.settings.bot_token_trading
            else None
        )

        self._bots = _Bots(alert=alert_bot, trading=trading_bot)
        self._lim_alert = AsyncRateLimiter(self.settings.max_messages_per_second) if alert_bot else None
        self._lim_trading = AsyncRateLimiter(self.settings.max_messages_per_second) if trading_bot else None

        self._task = loop.create_task(self._run(), name="telegram-worker")
        logger.info(
            "telegram worker started (alert=%s trading=%s)",
            bool(alert_bot),
            bool(trading_bot),
        )

    def _start_in_thread(self) -> None:
        """在后台线程中启动 Telegram worker"""
        self._thread = threading.Thread(target=self._thread_main, name="telegram-worker-thread", daemon=True)
        self._thread.start()
        logger.info("telegram worker started in background thread")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._start_in_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self.aclose())
            loop.close()

    async def aclose(self) -> None:
        """异步关闭 Telegram worker"""
        if self._task:
            self._task.cancel()

        if self._bots:
            if self._bots.alert:
                await self._bots.alert.close()
            if self._bots.trading:
                await self._bots.trading.close()

    def _should_send_opportunity_alert(self, message: Dict[str, Any]) -> bool:
        """判断是否满足正 EV 才发送 Alert Bot 消息"""
        # 只在 opportunity 类型消息且 net_ev > 0 时发送
        if message.get("type") == "opportunity":
            net_ev = message.get("data", {}).get("net_ev", 0.0)
            return net_ev > 0  # 只发送正 EV 的消息
        return False

    def publish(self, message: Dict[str, Any]) -> None:
        """线程安全、非阻塞的发布消息，超载丢弃"""
        if not self._started:
            self.start()

        if not self.settings.enabled or self._loop is None or self._queue is None:
            return

        msg_type = message.get("type")

        # Bot 1 (Alert): opportunity, error, recovery
        # Bot 2 (Trading): trade
        allowed_types = {"opportunity", "trade", "error", "recovery"}

        if msg_type not in allowed_types:
            return

        if msg_type == "opportunity":
            if not self._should_send_opportunity_alert(message):
                return

        try:
            payload = json.dumps(message, ensure_ascii=False)
        except Exception as exc:
            logger.exception("failed to json.dumps telegram message: %s", exc)
            return

        def _put_nowait() -> None:
            try:
                self._queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("telegram queue full, drop message")

        if self._loop.is_running():
            self._loop.call_soon_threadsafe(_put_nowait)

    async def _send_with_retry(self, bot: TelegramBotClient, text: str) -> None:
        """带重试逻辑的消息发送"""
        for attempt in range(self.settings.max_retries + 1):
            ok, err = await bot.send_text(text, parse_mode=None)
            if ok:
                return

            if attempt >= self.settings.max_retries:
                raise RuntimeError(err or "unknown send error")

            sleep_for = self.settings.retry_delay_seconds * (self.settings.retry_backoff ** attempt)
            logger.warning("telegram send failed attempt=%s err=%s sleep=%.2fs", attempt + 1, err, sleep_for)
            await asyncio.sleep(sleep_for)

    def _deadletter(self, raw: str, reason: str) -> None:
        """将无效消息记录到死信队列"""
        try:
            Path(self.settings.deadletter_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings.deadletter_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": int(time.time()), "reason": reason, "raw": raw}, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("failed to write deadletter")

    async def _run(self) -> None:
        """处理消息队列并发送"""
        assert self._queue is not None
        assert self._bots is not None

        while True:
            raw = await self._queue.get()

            try:
                obj = json.loads(raw)
            except Exception as exc:
                self._deadletter(raw, f"json_parse_error:{exc}")
                continue

            try:
                msg = _TELEGRAM_MESSAGE_ADAPTER.validate_python(obj)
            except ValidationError as exc:
                self._deadletter(raw, f"schema_validation_error:{exc}")
                continue

            text = format_message(msg)
            bot = None
            if isinstance(msg, OpportunityMessage):
                if not self._should_send_opportunity_alert(obj):
                    continue
                bot = self._bots.alert
            elif isinstance(msg, TradeMessage):
                bot = self._bots.trading
            elif isinstance(msg, (ErrorMessage, RecoveryMessage)):
                bot = self._bots.alert  # 错误/恢复消息发送到 Alert bot

            if bot:
                await self._send_with_retry(bot, text)
                logger.info("telegram sent %s message", obj.get("type"))
