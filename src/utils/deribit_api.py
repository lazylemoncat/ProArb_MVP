from typing import Optional

import httpx


BASE_URL = "https://www.deribit.com/api/v2"


async def get_spot_price(client: Optional[httpx.AsyncClient] = None):
    """获取 BTC 指数价格"""
    url = f"{BASE_URL}/public/get_index_price"
    params = {"index_name": "btc_usd"}
    data = await _get(url, params=params, client=client)
    return data["result"]["index_price"]


async def get_option_mid_price(
    instrument_name: str, client: Optional[httpx.AsyncClient] = None
):
    """获取期权盘口中间价(mid)"""
    url = f"{BASE_URL}/public/get_order_book"
    params = {"instrument_name": instrument_name}
    data = await _get(url, params=params, client=client)

    book = data["result"]
    bid = book.get("best_bid_price")
    ask = book.get("best_ask_price")

    if bid and ask:
        return (bid + ask) / 2
    elif bid:
        return bid
    elif ask:
        return ask
    else:
        return None


async def _get(
    url: str,
    params: Optional[dict[str, object]] = None,
    client: Optional[httpx.AsyncClient] = None,
):
    if client is not None:
        response = await client.get(url, params=params)
    else:
        async with httpx.AsyncClient(timeout=10.0) as local_client:
            response = await local_client.get(url, params=params)
    response.raise_for_status()
    return response.json()
