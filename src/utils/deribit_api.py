import requests


BASE_URL = "https://www.deribit.com/api/v2"


def get_spot_price():
    """获取 BTC 指数价格"""
    url = f"{BASE_URL}/public/get_index_price"
    params = {"index_name": "btc_usd"}
    r = requests.get(url, params=params).json()
    return r["result"]["index_price"]


def get_option_mid_price(instrument_name: str):
    """获取期权盘口中间价(mid)"""
    url = f"{BASE_URL}/public/get_order_book"
    params = {"instrument_name": instrument_name}
    r = requests.get(url, params=params).json()

    book = r["result"]
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
