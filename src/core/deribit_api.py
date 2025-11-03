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
    """获取 BTC 指数价格"""
    url = f"{BASE_URL}/public/get_index_price"
    params = {"index_name": symbol}
    r = requests.get(url, params=params).json()
    return r["result"]["index_price"]


async def get_mid_price_by_orderbook(websocket: ClientConnection, deribit_user_id, instrument_name: str):
    msg = {
        "id": deribit_user_id,
        "jsonrpc": "2.0",
        "method": "public/get_order_book",
        "params": {
            "depth": 5,
            "instrument_name": instrument_name
        }
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    data = json.loads(response).get("result")

    bid = data.get("best_bid_price")
    ask = data.get("best_ask_price")

    if bid and ask:
        return (bid + ask) / 2
    else:
        return data.get("mark_price")

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

async def get_initial_margin(websocket: ClientConnection, user_id: str, currency: str="BTC"):
    msg = {
        "id": user_id,
        "jsonrpc": "2.0",
        "method": "private/get_account_summary",
        "params":{
            "currency": currency,
            "extended": True
        }
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    response_dict = json.loads(response)
    initial_margin = response_dict.get("result").get("initial_margin")
    return initial_margin

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

async def get_margins(websocket, user_id, amount, instrument_name, price):
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
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    initial_margin = float(json.loads(response).get("result").get("buy"))

    return initial_margin

async def get_testnet_initial_margin(user_id, client_id, client_secret, amount, instrument_name):
    async with websockets.connect(TEST_WEBSOCKETS_URL) as websocket:
        await deribit_websocket_auth(websocket, user_id, client_id, client_secret)
        price = await get_mid_price_by_orderbook(websocket, user_id, instrument_name)

        initial_margin = await get_margins(websocket, user_id, amount, instrument_name, price)

        return initial_margin
    
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
        # async with websockets.connect(deribit_websockets_test_url) as websocket:
            # while websocket.state == websockets.protocol.State.OPEN:
            # response = await deribit_websocket_auth(websocket, client_id, client_secret)
            # response = await open_long_position(websocket, deribit_user_id, 40, "ETH-PERPETUAL")
            # pprint.pprint(json.loads(response))

            # initial_margin = await get_initial_margin(websocket, deribit_user_id, currency="ETH")
            # pprint.pprint(initial_margin)

            # response = await close_position(websocket, deribit_user_id, 40, "ETH-PERPETUAL")
            # pprint.pprint(json.loads(response))
        amount = 1
        instrument_name = "BTC-4NOV25-107000-C"
        
        initial_margin = await get_testnet_initial_margin(
            deribit_user_id, client_id, client_secret, 
            amount=amount, instrument_name=instrument_name
        )
        pprint.pprint(initial_margin)
    asyncio.run(call_api())