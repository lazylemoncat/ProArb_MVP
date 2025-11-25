import asyncio
import json
from typing import Literal

import ssl
import certifi
import websockets
from websockets.legacy.client import WebSocketClientProtocol, connect

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_TIMEOUT = 10.0  # WebSocket 等待 orderbook 的超时时间（秒）

# SSL 配置 - 使用 certifi 提供的 CA 证书
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

class PolymarketWS:
    """
    负责管理与 Polymarket CLOB 的 websocket 连接。

    特性：
    - 连接单例 + 复用
    - 使用锁保证并发安全
    - 带超时的 orderbook 拉取
    """

    _ws: WebSocketClientProtocol | None = None
    _lock: asyncio.Lock | None = None

    @classmethod
    async def _ensure_ws(cls) -> WebSocketClientProtocol:
        """
        确保有一个可用的 websocket 连接并返回它。
        """
        if cls._ws is None or getattr(cls._ws, "closed", False):
            cls._ws = await connect(CLOB_WS_URL, ssl=SSL_CONTEXT)

        if cls._lock is None:
            cls._lock = asyncio.Lock()
        if not cls._ws:
            raise Exception("can not connect polymarket websocket")

        return cls._ws
    
    @classmethod
    async def fetch_orderbook_once(
        cls,
        asset_id: str,
        side: Literal["buy", "sell"],
        timeout: float = WS_TIMEOUT,
    ) -> list[tuple[float, float]]:
        """
        不复用 websocket，每次调用单独建立连接获取一次 orderbook。

        用法与 fetch_orderbook 完全一致，但不会受到旧连接状态的影响。
        """
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")

        # 每次调用都新建连接，避免复用导致的超时 / 脏状态
        async with connect(CLOB_WS_URL) as ws:
            await ws.send(json.dumps({"assets_ids": [asset_id], "type": "market"}))

            while True:
                # raw_msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                raw_msg = await ws.recv()
                data = json.loads(raw_msg)

                # 兼容 list / dict 两种结构
                if isinstance(data, list):
                    if not data:
                        continue
                    data = data[0]

                if not isinstance(data, dict):
                    continue

                if data.get("event_type") != "book":
                    continue
                if data.get("asset_id") != asset_id:
                    continue

                raw_book = data.get("asks") if side == "buy" else data.get("bids")
                if not raw_book:
                    raise ValueError(f"Empty orderbook for asset_id {asset_id}")

                book: list[tuple[float, float]] = []
                for level in raw_book:
                    if not isinstance(level, dict):
                        continue
                    try:
                        price = float(level["price"])
                        size = float(level["size"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if price <= 0 or size <= 0:
                        continue
                    book.append((price, size))

                if not book:
                    raise ValueError(
                        f"No valid price levels in orderbook for asset_id {asset_id}"
                    )

                # 买单吃 ask：从低到高；卖单吃 bid：从高到低
                book.sort(key=lambda x: x[0], reverse=(side == "sell"))
                return book

    @classmethod
    async def fetch_orderbook(
        cls,
        asset_id: str,
        side: Literal["buy", "sell"],
    ) -> list[tuple[float, float]]:
        async with websockets.connect(CLOB_WS_URL) as ws:
            await ws.send(json.dumps({"assets_ids": [asset_id], "type": "market"}))

            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                if isinstance(data, list):
                    if len(data) == 0:
                        raise ValueError("Empty websocket data from Polymarket")
                    data = data[0]

                if data.get("event_type") != "book":
                    continue
                if data.get("asset_id") != asset_id:
                    continue

                # 先取原始的 orderbook 列表（还是 list[dict]）
                raw_book = data.get("asks", []) if side == "buy" else data.get("bids", [])
                if not raw_book:
                    raise ValueError(f"Empty orderbook for asset_id {asset_id}")

                book: list[tuple[float, float]] = []
                for level in raw_book:
                    if not isinstance(level, dict):
                        continue
                    try:
                        price = float(level["price"])
                        size = float(level["size"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if price <= 0 or size <= 0:
                        continue
                    book.append((price, size))

                if not book:
                    raise ValueError(
                        f"No valid price levels in orderbook for asset_id {asset_id}"
                    )

                # 买单吃 ask：从低到高；卖单吃 bid：从高到低
                book.sort(key=lambda x: x[0], reverse=(side == "sell"))
                return book

                    

    @classmethod
    async def close(cls) -> None:
        """
        主动关闭 websocket 连接（例如在服务关闭时调用）。
        """
        if cls._ws is not None and not getattr(cls._ws, "closed", False):
            await cls._ws.close()
        cls._ws = None
        cls._lock = None