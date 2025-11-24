from typing import Any, Dict

import requests

BASE_URL = "https://gamma-api.polymarket.com"
LIST_MARKET_URL = f"{BASE_URL}/markets"
PUBLIC_SEARCH_URL = f"{BASE_URL}/public-search"
GET_MARKET_BY_ID_URL = f"{BASE_URL}/markets/{{market_id}}"
GET_EVENT_BY_ID_URL = f"{BASE_URL}/events/{{event_id}}"

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
HTTP_TIMEOUT = 10  # 秒

class PolymarketAPI:
    @staticmethod
    def get_market_list() -> Dict[str, Any]:
        """获取所有市场列表"""
        response = requests.get(LIST_MARKET_URL, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_market_by_id(market_id: str) -> Dict[str, Any]:
        """根据市场 ID 获取市场详情"""
        url = GET_MARKET_BY_ID_URL.format(market_id=market_id)
        response = requests.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_market_public_search(querystring: str) -> Dict[str, Any]:
        """根据问题关键词搜索"""
        params = {"q": querystring}
        response = requests.get(PUBLIC_SEARCH_URL, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    
    @staticmethod
    def get_event_by_id(event_id: str) -> Dict[str, Any]:
        """根据 event_id 获取事件详情"""
        url = GET_EVENT_BY_ID_URL.format(event_id=event_id)
        response = requests.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()