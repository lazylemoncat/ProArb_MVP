from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any, Literal

import certifi
import requests
import websockets

BASE_URL = "https://gamma-api.polymarket.com"
LIST_MARKET_URL = f"{BASE_URL}/markets"
PUBLIC_SEARCH_URL = f"{BASE_URL}/public-search"
GET_MARKET_BY_ID_URL = f"{BASE_URL}/markets/{{market_id}}"
GET_EVENT_BY_ID_URL = f"{BASE_URL}/events/{{event_id}}"

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
HTTP_TIMEOUT = 10  # 秒

# SSL 配置 - 使用certifi提供的CA证书
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
REQUESTS_SESSION = requests.Session()
REQUESTS_SESSION.verify = certifi.where()

class PolymarketClient:
    """
    Polymarket HTTP API 封装：
    - 市场 / 事件查询
    - YES/NO 价格与 token id 获取
    """

    @staticmethod
    def get_market_list() -> Any:
        """获取所有市场列表"""
        response = REQUESTS_SESSION.get(LIST_MARKET_URL, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_market_by_id(market_id: str) -> Any:
        """根据市场 ID 获取市场详情"""
        url = GET_MARKET_BY_ID_URL.format(market_id=market_id)
        response = REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_market_public_search(querystring: str) -> Any:
        """根据问题关键词搜索市场"""
        params = {"q": querystring}
        response = REQUESTS_SESSION.get(PUBLIC_SEARCH_URL, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_event_id_public_search(querystring: str) -> str:
        """根据问题关键词搜索市场事件 ID"""
        response = PolymarketClient.get_market_public_search(querystring)
        events = response.get("events", [])
        if not events:
            raise ValueError(f"No events found for query {querystring}")
        event_id = events[0].get("id")
        if not event_id:
            raise ValueError(f"No event_id found for query {querystring}")
        return str(event_id)

    @staticmethod
    def get_event_by_id(event_id: str) -> Any:
        """根据 event_id 获取事件详情"""
        url = GET_EVENT_BY_ID_URL.format(event_id=event_id)
        response = REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    
    @staticmethod
    def get_markets_by_event_id(event_id: str) -> list[dict[str, Any]]:
        """
        根据 event_id 获取该事件下的所有 markets 列表。

        返回值示例（列表元素结构与 Gamma /events/{id} 中的单个 market 一致）：
        [
            {
                "id": "674533",
                "question": "...",
                "groupItemTitle": "96,000",
                "groupItemThreshold": "0",
                "clobTokenIds": "[\"...\", \"...\"]",
                ...
            },
            ...
        ]
        """
        event_data = PolymarketClient.get_event_by_id(event_id)
        markets = event_data.get("markets")

        if markets is None:
            raise ValueError(f"No markets found for event_id {event_id}")

        if not isinstance(markets, list):
            raise TypeError(
                f"Unexpected 'markets' type for event_id {event_id}: {type(markets).__name__}"
            )

        # 保证返回类型是 list[dict[str, Any]]
        return [m for m in markets if isinstance(m, dict)]

    @staticmethod
    def get_market_id_by_market_title(event_id: str, market_title: str) -> str:
        """根据 event_id 和 market_title 获取 market_id"""
        response = PolymarketClient.get_event_by_id(event_id)
        markets = response.get("markets", [])
        for market in markets:
            if market.get("groupItemTitle", "") == market_title:
                mid = market.get("id")
                if mid:
                    return str(mid)
        raise ValueError(
            f"No market_id found for event_id {event_id} with title {market_title}"
        )

    @staticmethod
    def get_clob_token_ids_by_market(market_id: str) -> dict[str, str]:
        """
        根据 market_id 获取 YES / NO 的 token ID。
        返回结构：
        {
            "market_id": "xxxxxx",
            "yes_token_id": "0xabc...",
            "no_token_id": "0xdef..."
        }
        """
        market_data = PolymarketClient.get_market_by_id(market_id)
        clob_tokens_raw = market_data.get("clobTokenIds")

        yes_token_id: str | None = None
        no_token_id: str | None = None

        if isinstance(clob_tokens_raw, str):
            try:
                tokens = json.loads(clob_tokens_raw)
                if isinstance(tokens, list) and len(tokens) >= 2:
                    yes_token_id, no_token_id = str(tokens[0]), str(tokens[1])
            except json.JSONDecodeError:
                pass
        elif isinstance(clob_tokens_raw, list):
            if len(clob_tokens_raw) >= 2:
                yes_token_id, no_token_id = str(clob_tokens_raw[0]), str(
                    clob_tokens_raw[1]
                )

        if yes_token_id is None or no_token_id is None:
            raise ValueError(
                f"No clob token ids found for market {market_id}: {clob_tokens_raw}"
            )

        return {
            "market_id": market_id,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
        }

    @staticmethod
    def get_yes_price(market_id: str) -> float:
        """通过 market_id 获取 Polymarket YES 价格(美元计价, 0-1)"""
        market_data = PolymarketClient.get_market_by_id(market_id)
        raw = market_data.get("outcomePrices", None)
        if raw is None:
            raise ValueError(f"No outcomePrices found for market {market_id}")
        try:
            if isinstance(raw, str):
                prices = json.loads(raw)
            else:
                prices = raw
            yes_price = float(prices[0])
        except Exception:
            raise ValueError(
                f"Invalid outcomePrices format for market {market_id}: {raw}"
            )
        return yes_price


# ============================================================
# WebSocket：滑点估算（原 get_polymarket_slippage.py）
# ============================================================

async def get_polymarket_slippage(
    asset_id: str,
    amount: float,
    side: Literal["buy", "sell"] = "buy",
    amount_type: Literal["usd", "shares"] = "usd",
) -> dict[str, float | str]:
    """
    基于当前 orderbook 估算 Polymarket 交易的滑点。:contentReference[oaicite:9]{index=9}

    amount_type = "usd"（默认） → 花多少 USD 吃单
    amount_type = "shares"     → 买/卖多少份额，而不是多少美元
    """
    async with websockets.connect(CLOB_WS_URL, ssl=SSL_CONTEXT) as ws:
        await ws.send(json.dumps({"assets_ids": [asset_id], "type": "market"}))

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            if isinstance(data, list):
                if len(data) == 0:
                    raise ValueError("Empty websocket data from Polymarket")
                data = data[0]

            if data.get("event_type") == "book" and data.get("asset_id") == asset_id:
                # Get both sides of the orderbook for spread calculation
                asks = sorted(data.get("asks", []), key=lambda x: float(x["price"]))
                bids = sorted(data.get("bids", []), key=lambda x: float(x["price"]), reverse=True)

                # Extract best_bid and best_ask
                best_ask = float(asks[0]["price"]) if asks else None
                best_bid = float(bids[0]["price"]) if bids else None
                mid_price = (best_ask + best_bid) / 2 if best_ask and best_bid else None
                spread = best_ask - best_bid if best_ask and best_bid else None

                # Select the correct side for execution simulation
                if side == "buy":
                    book = asks
                elif side == "sell":
                    book = bids
                else:
                    raise ValueError("side must be 'buy' or 'sell'")

                total_cost, total_size = 0.0, 0.0

                # 按 USD 或 shares 计算吃单
                if amount_type == "usd":
                    remaining_usd = amount
                    for lvl in book:
                        price = float(lvl["price"])
                        size = float(lvl["size"])
                        level_value = price * size

                        if remaining_usd >= level_value:
                            total_cost += level_value
                            total_size += size
                            remaining_usd -= level_value
                        else:
                            total_cost += remaining_usd
                            total_size += remaining_usd / price
                            remaining_usd = 0
                            break

                elif amount_type == "shares":
                    remaining_shares = amount
                    for lvl in book:
                        price = float(lvl["price"])
                        size = float(lvl["size"])

                        if remaining_shares >= size:
                            total_cost += size * price
                            total_size += size
                            remaining_shares -= size
                        else:
                            total_cost += remaining_shares * price
                            total_size += remaining_shares
                            remaining_shares = 0
                            break

                else:
                    raise ValueError("amount_type must be 'usd' or 'shares'")

                if total_size == 0:
                    raise ValueError("Insufficient liquidity")

                avg_price = total_cost / total_size
                best_price = float(book[0]["price"])
                if side == "buy":
                    slippage_pct = (avg_price - best_price) / best_price * 100
                else:
                    slippage_pct = (best_price - avg_price) / best_price * 100

                return {
                    "asset_id": asset_id,
                    "avg_price": round(avg_price, 6),
                    "shares_executed": round(total_size, 6),
                    "shares_bought": round(total_size, 6),
                    "total_cost_usd": round(total_cost, 6),
                    "slippage_pct": round(slippage_pct, 6),
                    "side": side,
                    "amount_type": amount_type,
                    # New fields for arbitrage precision
                    "best_ask": round(best_ask, 6) if best_ask else None,
                    "best_bid": round(best_bid, 6) if best_bid else None,
                    "mid_price": round(mid_price, 6) if mid_price else None,
                    "spread": round(spread, 6) if spread else None,
                }


def get_polymarket_slippage_sync(
    asset_id: str, amount: float, side: Literal["buy", "sell"] = "buy"
) -> dict[str, float | str]:
    """
    同步封装，便于在非 async 环境下快速调用滑点估算。
    默认按照 USD 规模吃单。
    """
    return asyncio.run(
        get_polymarket_slippage(asset_id, amount, side=side, amount_type="usd")
    )
