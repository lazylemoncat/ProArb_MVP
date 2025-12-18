import json
from typing import Literal

import ssl
import certifi
import websockets

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_TIMEOUT = 10.0  # WebSocket 等待 orderbook 的超时时间（秒）

# SSL 配置 - 使用 certifi 提供的 CA 证书
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

class PolymarketWS:
    @classmethod
    async def fetch_orderbook(
        cls,
        asset_id: str,
        side: Literal["ask", "bid"],
    ) -> list[tuple[float, float]]:
        async with websockets.connect(CLOB_WS_URL, ssl=SSL_CONTEXT) as ws:
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
                raw_book = data.get("asks", []) if side == "ask" else data.get("bids", [])
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
                book.sort(key=lambda x: x[0], reverse=(side == "bid"))
                return book