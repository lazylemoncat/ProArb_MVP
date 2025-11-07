import asyncio
import json
import os
import pprint

import dotenv
import requests
import websockets
from websockets import ClientConnection
from typing import Literal

BASE_URL = "https://www.deribit.com/api/v2"
WEBSOCKETS_URL = "wss://www.deribit.com/ws/api/v2"
TEST_WEBSOCKETS_URL = "wss://test.deribit.com/ws/api/v2"


def get_spot_price(symbol: Literal["btc_usd", "eth_usd"]="btc_usd"):
    """
    获取 BTC 指数价格
    Return:
        BTC 指数价格(USD)
    """
    url = f"{BASE_URL}/public/get_index_price"
    params = {"index_name": symbol}
    r = requests.get(url, params=params).json()
    return r["result"]["index_price"]


async def get_mid_price_by_orderbook(websocket: ClientConnection, deribit_user_id, instrument_name: str, depth: int=20):
    """
    获取 orderbook 的中间价
    Return:
        orderbook 的中间价(BTC)
    """
    msg = {
        "id": deribit_user_id,
        "jsonrpc": "2.0",
        "method": "public/get_order_book",
        "params": {
            "depth": depth,
            "instrument_name": instrument_name
        }
    }
    try:
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        data = json.loads(response).get("result")

        bid = data.get("best_bid_price")
        ask = data.get("best_ask_price")

        if bid and ask:
            return (bid + ask) / 2
        else:
            return data.get("mark_price")
    except Exception as e:
        raise Exception(f"get_mid_price_by_orderbook wrong: {e}, {data}, {response}")

async def get_orderbook(instrument_name, depth=1000):
    async with websockets.connect(TEST_WEBSOCKETS_URL) as websocket:
        msg = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "public/get_order_book",
            "params": {"instrument_name": instrument_name, "depth": depth}
        }
        await websocket.send(json.dumps(msg))
        resp = json.loads(await websocket.recv())["result"]
        return resp["bids"], resp["asks"], resp["best_bid_price"], resp["best_ask_price"]
    
def calc_slippage(orderbook, amount, side: str):
    """
    side='buy' → 买入(吃 ask)
    side='sell' → 卖出(吃 bid)
    """
    bids, asks, best_bid, best_ask = orderbook
    remaining = amount
    filled_value = 0
    filled_amount = 0

    if side == "buy":
        target_price = best_ask
        for price, qty in asks:
            if remaining <= 0:
                break
            take = min(remaining, qty)
            filled_value += take * price
            remaining -= take

    elif side == "sell":
        target_price = best_bid
        for price, qty in bids:
            if remaining <= 0:
                break
            take = min(remaining, qty)
            filled_value += take * price
            remaining -= take
    
    filled_amount = amount - remaining

    if filled_amount == 0:
        return None, None, target_price, "no_liquidity"

    # if remaining > 0:
    #     raise Exception("not enough depth") # 深度不足

    avg_price = filled_value / amount
    slippage = (avg_price - target_price) / target_price

    return slippage, avg_price, target_price, "partial" if remaining > 0 else "filled"

async def deribit_websocket_auth(websocket: ClientConnection, deribit_user_id: str, client_id: str, client_secret: str):
    msg = {
        "id": deribit_user_id,
        "jsonrpc":"2.0",
        "method":"public/auth",
        "params":{
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response

async def open_long_position(websocket: ClientConnection, user_id: str, amount: int, instrument_name: str, type: str="market"):
    msg = {
        "id": user_id,
        "jsonrpc": "2.0",
        "method": "private/buy",
        "params": {
            "amount": amount,
            "instrument_name": instrument_name,
            "type": type
        }
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response

async def close_position(websocket: ClientConnection, user_id: str, amount: int, instrument_name: str, type: str="market"):
    msg = {
        "id": user_id,
        "jsonrpc": "2.0",
        "method": "private/sell",
        "params": {
            "amount": amount,
            "instrument_name": instrument_name,
            "type": type
        }
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response

async def change_margin_model(websocket, user_id, margin_model: str="cross_pm"):
    msg = {
        "id": user_id,
        "jsonrpc": "2.0",
        "method": "private/change_margin_model",
        "params": {
            "margin_model": "cross_pm",
            "user_id": user_id
        }
    }
    try:
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        response_result = json.loads(response).get("result")
    except Exception as e:
        raise Exception(f"change_margin_model wrong: {e}, {response_result}, {response}")

async def get_margins(websocket, user_id, amount, instrument_name, price):
    """
    获取初始保证金
    Args:
        price: BTC 单位的价格(BTC)
    Return:
        初始保证金(USD)
    """
    msg = {
            "id": user_id,
            "jsonrpc":"2.0",
            "method":"private/get_margins",
            "params":{
                "amount": amount,
                "instrument_name": instrument_name,
                "price": price
            }
        }
    try:
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        response_result = json.loads(response).get("result")
        initial_margin = float(response_result.get("buy"))
    except Exception as e:
        raise Exception(f"initial_margin wrong: {e}, {response_result}, {response}, {price}")

    return initial_margin

async def get_testnet_initial_margin(user_id, client_id, client_secret, amount, instrument_name):
    async with websockets.connect(TEST_WEBSOCKETS_URL) as websocket:
        await deribit_websocket_auth(websocket, user_id, client_id, client_secret)
        await change_margin_model(websocket, user_id)
        price = await get_mid_price_by_orderbook(websocket, user_id, instrument_name)
        
        initial_margin = await get_margins(websocket, user_id, amount, instrument_name, price)

        # 返回的是 BTC, 需要乘以 spot price才是 USD
        return initial_margin
    
async def get_interest_rate(user_id, instrument_name):
    async with websockets.connect(TEST_WEBSOCKETS_URL) as websocket:
        msg = {
            "id": user_id,
            "jsonrpc": "2.0",
            "method": "public/get_book_summary_by_instrument",
            "params": {
                "instrument_name": instrument_name
            }
        }
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        pprint.pprint(json.loads(response))
        interest_rate = float(json.loads(response).get("result")[0].get("interest_rate"))

        return interest_rate

async def get_simulate_portfolio_initial_margin(user_id, client_id, client_secret, currency, simulated_positions):
    msg = {
        "id": user_id,
        "jsonrpc": "2.0",
        "method": "private/simulate_portfolio",
        "params": {
            "add_positions": True,
            "currency": currency,
            "simulated_positions": simulated_positions
        }
    }
    async with websockets.connect(TEST_WEBSOCKETS_URL) as websocket:
        await deribit_websocket_auth(websocket, user_id, client_id, client_secret)
        await change_margin_model(websocket, user_id)
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        return json.loads(response)["result"]["initial_margin"]

    
if __name__ == "__main__":
    import asyncio
    import json
    import os
    import pprint

    import dotenv
    import websockets

    dotenv.load_dotenv()

    # deribit_user_id = os.getenv("deribit_user_id", "")
    # client_id = os.getenv("deribit_client_id", "")
    # client_secret = os.getenv("deribit_client_secret", "")

    deribit_user_id = os.getenv("test_deribit_user_id", "")
    client_id = os.getenv("test_deribit_client_id", "")
    client_secret = os.getenv("test_deribit_client_secret", "")

    async def call_api():
        instrument_name = "BTC-28NOV25-104000-C"
        instrument_name2 = "BTC-28NOV25-100000-C"
        amount1 = 100
        amount2 = 100
        res = await get_simulate_portfolio_initial_margin(
            user_id=deribit_user_id,
            client_id=client_id,
            client_secret=client_secret,
            currency="BTC",
            simulated_positions= {
                instrument_name: amount1,
                instrument_name2: -amount2
            }
        )
        print(res)
    asyncio.run(call_api())