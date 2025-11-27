import json
from typing import Any

from .polymarket_api import PolymarketAPI


class PolymarketClient:
    """
    - 市场 / 事件查询
    - YES/NO 价格与 token id 获取
    """
    @staticmethod
    def get_event_id_public_search(querystring: str) -> str:
        """根据问题关键词搜索市场事件 ID"""
        response = PolymarketAPI.get_market_public_search(querystring)
        events = response.get("events", [])
        if not events:
            raise ValueError(f"No events found for query {querystring}")
        event_id = events[0].get("id")
        if not event_id:
            raise ValueError(f"No event_id found for query {querystring}")
        return str(event_id)
    
    @staticmethod
    def get_markets_by_event_id(event_id: str) -> list[dict[str, Any]]:
        """
        根据 event_id 获取该事件下的所有 markets 列表。
        """
        event_data = PolymarketAPI.get_event_by_id(event_id)
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
        response = PolymarketAPI.get_event_by_id(event_id)
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
    def get_market_data_by_market_title(event_id: str, market_title: str):
        market_id = PolymarketClient.get_market_id_by_market_title(event_id, market_title)
        return PolymarketAPI.get_market_by_id(market_id)

    @staticmethod
    def get_clob_token_ids_by_market_id(market_id: str) -> dict[str, str]:
        """
        根据 market_id 获取 YES / NO 的 token ID。
        返回结构：
        {
            "market_id": "xxxxxx",
            "yes_token_id": "0xabc...",
            "no_token_id": "0xdef..."
        }
        """
        market_data = PolymarketAPI.get_market_by_id(market_id)
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
    def get_clob_token_ids_by_market_title(event_id, market_title) -> dict[str, str]:
        market_id = PolymarketClient.get_market_id_by_market_title(event_id, market_title)
        return PolymarketClient.get_clob_token_ids_by_market_id(market_id)

    @staticmethod
    def get_yes_price(market_id: str) -> float:
        """通过 market_id 获取 Polymarket YES 价格(美元计价, 0-1)"""
        market_data = PolymarketAPI.get_market_by_id(market_id)
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
    
    @staticmethod
    def get_event_by_id(event_id: str):
        return PolymarketAPI.get_event_by_id(event_id=event_id)
