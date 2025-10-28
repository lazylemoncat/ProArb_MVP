import json
from typing import Any
import requests


class PolymarketAPI:
    BASE_URL = "https://gamma-api.polymarket.com"
    list_market_url = f"{BASE_URL}/markets"
    public_search_url = f"{BASE_URL}/public-search"
    get_market_by_id_url = f"{BASE_URL}/markets/{{market_id}}"
    get_event_by_id_url = f"{BASE_URL}/events/{{event_id}}"

    @staticmethod
    def get_yes_price(market_id: str) -> float:
        """通过 market_id 获取 Polymarket YES 价格(美元计价, 0-1)"""
        market_data = PolymarketAPI.get_market_by_id(market_id)
        raw = market_data.get("outcomePrices", None)
        if raw is None:
            raise ValueError(f"No outcomePrices found for market {market_id}")
        try:
            prices = json.loads(raw)
            yes_price = float(prices[0])
        except Exception:
            raise ValueError(f"Invalid outcomePrices format for market {market_id}: {raw}")
        return yes_price

    @staticmethod
    def get_market_list() -> Any:
        """获取所有市场列表"""
        response = requests.get(PolymarketAPI.list_market_url)
        return response.json()

    @staticmethod
    def get_market_by_id(market_id: str) -> Any:
        """根据市场 ID 获取市场详情"""
        url = PolymarketAPI.get_market_by_id_url.format(market_id=market_id)
        response = requests.get(url)
        return response.json()

    @staticmethod
    def get_market_public_search(querystring: str) -> Any:
        """根据问题关键词搜索市场"""
        params = {"q": querystring}
        response = requests.get(PolymarketAPI.public_search_url, params=params)
        return response.json()

    @staticmethod
    def get_event_id_public_search(querystring: str) -> Any:
        """根据问题关键词搜索市场事件 ID"""
        response = PolymarketAPI.get_market_public_search(querystring)
        event_id = response.get("events", [])[0].get("id", None)
        if event_id is None:
            raise ValueError(f"No event_id found for query {querystring}")
        return event_id

    @staticmethod
    def get_event_by_id(event_id: str) -> Any:
        """根据 event_id 获取事件详情"""
        url = PolymarketAPI.get_event_by_id_url.format(event_id=event_id)
        response = requests.get(url)
        return response.json()

    @staticmethod
    def get_market_id_by_market_title(event_id: str, market_title: str) -> str:
        """根据 event_id 和 market_title 获取 market_id"""
        response = PolymarketAPI.get_event_by_id(event_id)
        markets = response.get("markets", [])
        for market in markets:
            if market.get("groupItemTitle", "") == market_title:
                return market.get("id", "")
        raise ValueError(f"No market_id found for event_id {event_id} with title {market_title}")

    # ✅ 新增函数：根据 market_id 获取 YES / NO token IDs
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
        market_data = PolymarketAPI.get_market_by_id(market_id)
        clob_tokens_raw = market_data.get("clobTokenIds")

        yes_token_id, no_token_id = None, None

        if isinstance(clob_tokens_raw, str):
            try:
                tokens = json.loads(clob_tokens_raw)
                if isinstance(tokens, list) and len(tokens) >= 2:
                    yes_token_id, no_token_id = tokens[0], tokens[1]
            except json.JSONDecodeError:
                pass
        elif isinstance(clob_tokens_raw, list):
            if len(clob_tokens_raw) >= 2:
                yes_token_id, no_token_id = clob_tokens_raw[0], clob_tokens_raw[1]

        if yes_token_id is None or no_token_id is None:
            raise ValueError(f"No clob token ids found for market {market_id}: {clob_tokens_raw}")

        return {
            "market_id": market_id,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id
        }
