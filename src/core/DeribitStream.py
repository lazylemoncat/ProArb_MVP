import asyncio
import json

import requests
import websockets
from typing import Literal

DERIBIT_WS = "wss://www.deribit.com/ws/api/v2"


class DeribitStream:
    def __init__(self, on_index_price=None, on_option_quote=None):
        self.on_index_price = on_index_price
        self.on_option_quote = on_option_quote
        self.connected = False
        self.instruments_to_sub = set()

    async def _connect(self):
        while True:
            try:
                print("🔗 Connecting to Deribit WebSocket...")
                async with websockets.connect(DERIBIT_WS, ping_interval=20) as ws:
                    self.ws = ws   # ✅ 保存 ws 实例
                    self.connected = True
                    print("✅ Connected to Deribit WebSocket")

                    # ✅ 订阅 BTC 指数价格
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "public/subscribe",
                        "params": {
                            "channels": ["deribit_price_index.btc_usd"]
                        }
                    }))

                    # ✅ 等 main 传入合约后再订阅（延迟发）
                    await asyncio.sleep(1)

                    # ⭐ 在这里自动订阅 K1/K2 期权盘口
                    if hasattr(self, "instruments_to_sub"):
                        for inst in self.instruments_to_sub:
                            print(f"📡 Subscribing order book: {inst}")
                            await ws.send(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "public/subscribe",
                                "params": {
                                    "channels": [f"book.{inst}.none.1.100ms"]
                                }
                            }))

                    # === 保持实时接收 ===
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        # 指数回调
                        if "params" in data and "deribit_price_index" in data["params"]["channel"]:
                            index_price = data["params"]["data"]["price"]
                            if self.on_index_price:
                                self.on_index_price(index_price)

                        # 期权盘口回调
                        if "params" in data and "book." in data["params"]["channel"]:
                            book = data["params"]["data"]
                            bids = book.get("bids", [])
                            asks = book.get("asks", [])
                            bid = bids[0][0] if bids else None
                            ask = asks[0][0] if asks else None
                            mid = (bid + ask) / 2 if bid and ask else None

                            if self.on_option_quote:
                                self.on_option_quote(inst, bid, ask, mid)

            except Exception as e:
                print("⚠️ WebSocket Error, reconnecting in 3s:", e)
                self.connected = False
                await asyncio.sleep(3)

    async def subscribe_option(self, ws, instrument_name: str):
        """订阅期权盘口（bid/ask价格实时更新）"""
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "public/subscribe",
            "params": {
                "channels": [f"book.{instrument_name}.none.1.100ms"]
            }
        }))

    def start(self):
        loop = asyncio.new_event_loop()     # 创建新的事件循环
        asyncio.set_event_loop(loop)        # 绑定到当前线程
        loop.run_until_complete(self._connect())   # 运行推流

    @staticmethod
    def find_option_instrument(strike: float, currency: Literal["BTC", "ETH"] = "BTC", call: bool = True):
        """
        根据行权价找到最近的可行权价期权, 并选取最近到期(T最小)的 Call/Put。
        """
        url = "https://www.deribit.com/api/v2/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}
        r = requests.get(url, params=params).json()
        instruments = r["result"]

        callput = "call" if call else "put"

        # 先筛出同方向的期权
        same_type = [inst for inst in instruments if inst["option_type"] == callput]

        # 找到与目标 strike 差值最小的实际可交易行权价
        # Deribit strike 类型为 float → 防止 int 比较失败
        best_strike = min({inst["strike"] for inst in same_type},
                        key=lambda s: abs(s - float(strike)))

        # 过滤出同一次strike的合约
        candidates = [inst for inst in same_type if inst["strike"] == best_strike]

        if not candidates:
            raise ValueError(f"⚠️ 无法找到与行权价 {strike} 相近的可用期权")

        # 选最近到期的
        candidates.sort(key=lambda x: x["expiration_timestamp"])
        instrument_name = candidates[0]["instrument_name"]
        expiration_timestamp = candidates[0]["expiration_timestamp"]

        print(f"🎯 行权价 {strike} → 使用最近可交易行权价 {best_strike} → 合约 {instrument_name}")
        return (instrument_name, expiration_timestamp)