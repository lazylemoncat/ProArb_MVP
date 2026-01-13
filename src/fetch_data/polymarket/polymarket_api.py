import json
import logging
import time
from typing import Any, Dict, Tuple

import ssl
import certifi
import requests
from requests.exceptions import RequestException, HTTPError

from src.utils.dataloader.env_loader import load_env_config

BASE_URL = "https://gamma-api.polymarket.com"
LIST_MARKET_URL = f"{BASE_URL}/markets"
LIST_EVENT_URL = f"{BASE_URL}/events"
PUBLIC_SEARCH_URL = f"{BASE_URL}/public-search"
GET_MARKET_BY_ID_URL = f"{BASE_URL}/markets/{{market_id}}"
GET_EVENT_BY_ID_URL = f"{BASE_URL}/events/{{event_id}}"

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
HTTP_TIMEOUT = 10  # 秒

# Load retry configuration from environment variables
env_config = load_env_config()
MAX_RETRIES = env_config.MAX_RETRIES
RETRY_DELAY_SECONDS = env_config.RETRY_DELAY_SECONDS
RETRY_BACKOFF = env_config.RETRY_BACKOFF

# Generate exponential backoff delays based on env config
RETRY_DELAYS = [RETRY_DELAY_SECONDS * (RETRY_BACKOFF ** i) for i in range(MAX_RETRIES)]

# SSL 配置 - 使用 certifi 提供的 CA 证书
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
REQUESTS_SESSION = requests.Session()
REQUESTS_SESSION.verify = certifi.where()

logger = logging.getLogger(__name__)


def _retry_request(func):
    """Decorator to add retry logic with exponential backoff to API requests"""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                response = func(*args, **kwargs)
                response.raise_for_status()
                return response
            except HTTPError as e:
                last_exception = e
                # Don't retry on 4xx client errors (except 429 rate limit)
                if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    logger.warning(f"Client error {e.response.status_code}, not retrying: {e}")
                    raise

                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Request failed after {MAX_RETRIES} attempts: {e}")
            except RequestException as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(f"Network error (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Network error after {MAX_RETRIES} attempts: {e}")

        # If all retries failed, raise the last exception
        raise last_exception

    return wrapper

class PolymarketAPI:
    @staticmethod
    def get_market_list(closed: bool = False, offset: int = 0) -> list[Dict[str, Any]]:
        """获取所有市场列表"""
        url = LIST_MARKET_URL + "?closed=" + str(closed) + "&offset=" + str(offset)

        @_retry_request
        def _request():
            return REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)

        response = _request()
        return response.json()

    @staticmethod
    def get_event_list(closed: bool = False, offset: int = 0) -> list[Dict[str, Any]]:
        """获取所有事件列表"""
        url = LIST_EVENT_URL + "?closed=" + str(closed) + "&offset=" + str(offset)

        @_retry_request
        def _request():
            return REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)

        response = _request()
        return response.json()

    @staticmethod
    def get_market_by_id(market_id: str) -> Dict[str, Any]:
        """根据市场 ID 获取市场详情"""
        url = GET_MARKET_BY_ID_URL.format(market_id=market_id)

        @_retry_request
        def _request():
            return REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)

        response = _request()
        return response.json()

    @staticmethod
    def get_market_public_search(querystring: str) -> Dict[str, Any]:
        """根据问题关键词搜索"""
        params = {"q": querystring}

        @_retry_request
        def _request():
            return REQUESTS_SESSION.get(PUBLIC_SEARCH_URL, params=params, timeout=HTTP_TIMEOUT)

        response = _request()
        return response.json()

    @staticmethod
    def get_event_by_id(event_id: str) -> Dict[str, Any]:
        """根据 event_id 获取事件详情"""
        url = GET_EVENT_BY_ID_URL.format(event_id=event_id)

        @_retry_request
        def _request():
            return REQUESTS_SESSION.get(url, timeout=HTTP_TIMEOUT)

        response = _request()
        return response.json()
    
    @staticmethod
    def get_prices(market_id: str) -> Tuple[float, float]:
        market_data = PolymarketAPI.get_market_by_id(market_id)
        raw = market_data.get("outcomePrices", None)
        if raw is None:
            raise ValueError(f"No outcomePrices found for market {market_id}")
        try:
            if isinstance(raw, str):
                prices: list[str] = json.loads(raw)
            else:
                prices = raw
            yes_price = float(prices[0])
            no_prices = float(prices[1])
        except Exception:
            raise ValueError(
                f"Invalid outcomePrices format for market {market_id}: {raw}"
            )
        return yes_price, no_prices
    
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