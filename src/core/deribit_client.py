from __future__ import annotations

import asyncio
import datetime
import json
from dataclasses import dataclass
from typing import Any, Literal

import requests
import websockets
from websockets import ClientConnection

BASE_URL = "https://www.deribit.com/api/v2"
WS_URL = "wss://www.deribit.com/ws/api/v2"
TEST_WS_URL = "wss://test.deribit.com/ws/api/v2"

DERIBIT_WS = WS_URL
HTTP_TIMEOUT = 10  # 秒

# ============================================================
# 基础配置对象
# ============================================================

@dataclass
class DeribitUserCfg:
    user_id: str
    client_id: str
    client_secret: str


# ============================================================
# HTTP API：指数价格 / 期权列表
# ============================================================

def get_spot_price(index_name: Literal["btc_usd", "eth_usd"] = "btc_usd") -> float:
    """
    获取 BTC / ETH 指数现货价格（USD）。
    """
    url = f"{BASE_URL}/public/get_index_price"
    params = {"index_name": index_name}
    r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return float(data["result"]["index_price"])


def get_deribit_option_data(
    currency: str = "BTC",
    kind: str = "option",
    base_fee_btc: float = 0.0003,
    base_fee_eth: float = 0.0003,
    usdc_settled: bool = False,
    amount: float = 1.0,
) -> list[dict[str, float | str]]:
    """
    获取 Deribit 期权数据并计算 mark_iv、手续费、Bid/Ask。

    返回的 bid_price / ask_price 为期权价格，以标的计价（例如 BTC / ETH）。
    """
    url = f"{BASE_URL}/public/get_book_summary_by_currency"
    resp = requests.get(url, params={"currency": currency, "kind": kind}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    results: list[dict[str, float | str]] = []
    for item in data.get("result", []):
        try:
            option_name = str(item.get("instrument_name"))
            mark_iv = float(item.get("mark_iv"))
            bid_price = float(item.get("bid_price"))
            ask_price = float(item.get("ask_price"))
            option_price = float(item.get("last") or 0.0)
            index_price = float(item.get("underlying_price"))

            # 手续费计算逻辑：直接沿用你原来的实现
            if not usdc_settled:
                base_fee = base_fee_btc if currency.upper() == "BTC" else base_fee_eth
                fee = max(base_fee, 0.125 * option_price) * amount
            else:
                fee = max(0.0003 * index_price, 0.125 * option_price) * amount

            results.append(
                {
                    "instrument_name": option_name,
                    "mark_iv": mark_iv,
                    "bid_price": bid_price,
                    "ask_price": ask_price,
                    "fee": fee,
                }
            )
        except (TypeError, ValueError):
            # 某条脏数据就直接跳过
            continue

    return results


# ============================================================
# 推流 + 按行权价找合约（原 DeribitStream）
# ============================================================

class DeribitStream:
    """
    Deribit WebSocket 推流封装 + 静态工具方法（按行权价找合约）。:contentReference[oaicite:3]{index=3}
    """

    def __init__(self, on_index_price=None, on_option_quote=None):
        self.on_index_price = on_index_price
        self.on_option_quote = on_option_quote
        self.connected = False
        self.instruments_to_sub = set()
        self.ws: ClientConnection | None = None

    async def _connect(self) -> None:
        while True:
            try:
                print("🔗 Connecting to Deribit WebSocket...")
                async with websockets.connect(DERIBIT_WS, ping_interval=20) as ws:
                    self.ws = ws
                    self.connected = True
                    print("✅ Connected to Deribit WebSocket")

                    # 订阅 BTC 指数价格
                    await ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "public/subscribe",
                                "params": {"channels": ["deribit_price_index.btc_usd"]},
                            }
                        )
                    )

                    # 等 main 传入合约后再订阅 orderbook
                    await asyncio.sleep(1)

                    if hasattr(self, "instruments_to_sub"):
                        for inst in self.instruments_to_sub:
                            print(f"📡 Subscribing order book: {inst}")
                            await ws.send(
                                json.dumps(
                                    {
                                        "jsonrpc": "2.0",
                                        "id": 2,
                                        "method": "public/subscribe",
                                        "params": {
                                            "channels": [f"book.{inst}.none.1.100ms"]
                                        },
                                    }
                                )
                            )

                    # 实时接收
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        # 指数回调
                        if (
                            "params" in data
                            and "deribit_price_index" in data["params"]["channel"]
                        ):
                            index_price = data["params"]["data"]["price"]
                            if self.on_index_price:
                                self.on_index_price(index_price)

                        # 期权盘口回调
                        if (
                            "params" in data
                            and data["params"]["channel"].startswith("book.")
                        ):
                            book = data["params"]["data"]
                            channel = data["params"]["channel"]
                            # channel: "book.BTC-28NOV25-104000-C.none.1.100ms"
                            inst = channel.split(".")[1]

                            bids = book.get("bids", [])
                            asks = book.get("asks", [])
                            bid = bids[0][0] if bids else None
                            ask = asks[0][0] if asks else None
                            mid = (
                                (bid + ask) / 2
                                if (bid is not None and ask is not None)
                                else None
                            )

                            if self.on_option_quote:
                                self.on_option_quote(inst, bid, ask, mid)

            except Exception as e:
                print("⚠️ WebSocket Error, reconnecting in 3s:", e)
                self.connected = False
                await asyncio.sleep(3)

    async def subscribe_option(
        self, ws: ClientConnection, instrument_name: str
    ) -> None:
        """订阅期权盘口（bid/ask 价格实时更新）"""
        await ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "public/subscribe",
                    "params": {"channels": [f"book.{instrument_name}.none.1.100ms"]},
                }
            )
        )

    def start(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._connect())

    # ---------- 静态工具函数：按行权价找合约 ----------
    @staticmethod
    def find_option_instrument(
        strike: float,
        currency: Literal["BTC", "ETH"] = "BTC",
        call: bool = True,
        day_offset: int = 0,
        exp_timestamp: float | None = None,
    ):
        """
        根据行权价找到最近的可交易期权。

        参数：
            strike: 目标行权价（可以是理论值，函数会自动映射到实际挂牌行权价）
            currency: "BTC" 或 "ETH"
            call: True 为看涨期权，False 为看跌
            day_offset: 当未提供 exp_timestamp 时，表示在该行权价下按到期时间排序后的第几个合约
            exp_timestamp: 若提供（单位：毫秒），将优先选择 expiration_timestamp
                           最接近该值的合约，忽略 day_offset

        返回：
            instrument_name, expiration_timestamp
        """
        url = f"{BASE_URL}/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        instruments = r.json()["result"]

        option_type = "call" if call else "put"

        same_type = [inst for inst in instruments if inst["option_type"] == option_type]
        if not same_type:
            raise ValueError(f"无 {currency} {option_type} 期权可用")

        # 所有可交易行权价集合
        strikes = {float(inst["strike"]) for inst in same_type}

        # 找与目标 strike 最接近的真实行权价
        best_strike = min(strikes, key=lambda s: abs(s - float(strike)))

        # 过滤出这一档行权价下的所有到期日合约
        candidates = [
            inst for inst in same_type if float(inst["strike"]) == best_strike
        ]
        if not candidates:
            raise ValueError(f"无法找到行权价 {strike} 附近的期权（货币: {currency}）")

        # 按到期时间升序
        candidates.sort(key=lambda x: x["expiration_timestamp"])

        if exp_timestamp is not None:
            # 选择 expiration_timestamp 最接近指定时间的合约
            selected = min(
                candidates,
                key=lambda x: abs(x["expiration_timestamp"] - exp_timestamp),
            )
        else:
            if day_offset >= len(candidates):
                day_offset = 0
            selected = candidates[day_offset]

        instrument_name = selected["instrument_name"]
        expiration_timestamp = selected["expiration_timestamp"]

        print(
            f"🎯 行权价 {strike} → 使用最近可交易行权价 {best_strike} → 合约 {instrument_name}"
        )
        return instrument_name, expiration_timestamp

    @staticmethod
    def find_month_future_by_strike(
        strike: float, currency: Literal["BTC", "ETH"] = "BTC", call: bool = True
    ):
        """
        根据行权价找到最接近的行权价，
        并在【每月最后一个周五（月度期权）】中选取最近到期的 Call/Put。
        """
        url = f"{BASE_URL}/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT).json()
        instruments = r["result"]

        callput = "call" if call else "put"
        same_type = [inst for inst in instruments if inst["option_type"] == callput]
        if not same_type:
            raise ValueError(f"⚠️ 无法找到任何 {currency} {callput} 期权合约")

        def is_last_friday(timestamp_ms: int) -> bool:
            dt = datetime.datetime.utcfromtimestamp(timestamp_ms / 1000)
            if dt.weekday() != 4:  # 4 = Friday
                return False
            next_week = dt + datetime.timedelta(days=7)
            return next_week.month != dt.month

        same_type = [
            inst for inst in same_type if is_last_friday(inst["expiration_timestamp"])
        ]
        if not same_type:
            raise ValueError("⚠️ 当前没有找到任何月度期权（每月最后一个周五）")

        best_strike = min(
            {inst["strike"] for inst in same_type},
            key=lambda s: abs(s - float(strike)),
        )

        candidates = [inst for inst in same_type if inst["strike"] == best_strike]
        if not candidates:
            raise ValueError(f"⚠️ 没有找到与行权价 {strike} 接近的月度期权")

        candidates.sort(key=lambda x: x["expiration_timestamp"])
        instrument_name = candidates[0]["instrument_name"]
        expiration_timestamp = candidates[0]["expiration_timestamp"]

        print(
            f"🎯 行权价 {strike} → 月度合约行权价 {best_strike} → 合约 {instrument_name}"
        )
        return instrument_name, expiration_timestamp


# ============================================================
# WebSocket：Orderbook / 保证金 / 组合模拟（原 deribit_api.py）
# ============================================================

async def get_mid_price_by_orderbook(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    instrument_name: str,
    depth: int = 20,
) -> float:
    """
    获取 orderbook 的中间价（标的单位，如 BTC）。:contentReference[oaicite:4]{index=4}
    """
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "public/get_order_book",
        "params": {"depth": depth, "instrument_name": instrument_name},
    }
    response = None
    data: dict[str, Any] | None = None
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


async def get_orderbook(
    instrument_name: str, depth: int = 1000
) -> tuple[list[list[float]], list[list[float]], float, float]:
    """
    从 Deribit 测试网获取指定合约的 orderbook。
    返回 (bids, asks, best_bid, best_ask)
    """
    async with websockets.connect(TEST_WS_URL) as websocket:
        msg = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "public/get_order_book",
            "params": {"instrument_name": instrument_name, "depth": depth},
        }
        await websocket.send(json.dumps(msg))
        resp = json.loads(await websocket.recv())["result"]
        return (
            resp["bids"],
            resp["asks"],
            resp["best_bid_price"],
            resp["best_ask_price"],
        )


def calc_slippage(
    orderbook: tuple[list[list[float]], list[list[float]], float, float],
    amount: float,
    side: str,
):
    """
    计算在给定 orderbook 上吃单 amount 的滑点。

    side='buy' → 买入(吃 ask)
    side='sell' → 卖出(吃 bid)
    """
    bids, asks, best_bid, best_ask = orderbook
    remaining = amount
    filled_value = 0.0

    if side == "buy":
        target_price = best_ask
        book_side = asks
    elif side == "sell":
        target_price = best_bid
        book_side = bids
    else:
        raise ValueError("side must be 'buy' or 'sell'")

    filled_amount = 0.0
    for price, qty in book_side:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        filled_value += take * price
        remaining -= take
        filled_amount += take

    if filled_amount == 0:
        return None, None, target_price, "no_liquidity"

    avg_price = filled_value / filled_amount
    slippage = (avg_price - target_price) / target_price

    return slippage, avg_price, target_price, "partial" if remaining > 0 else "filled"


async def deribit_websocket_auth(
    websocket: ClientConnection, deribitUserCfg: DeribitUserCfg
) -> str:
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "public/auth",
        "params": {
            "client_id": deribitUserCfg.client_id,
            "client_secret": deribitUserCfg.client_secret,
            "grant_type": "client_credentials",
        },
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response


async def open_long_position(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    amount: int,
    instrument_name: str,
    type: str = "market",
) -> str:
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "private/buy",
        "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response


async def close_position(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    amount: int,
    instrument_name: str,
    type: str = "market",
) -> str:
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "private/sell",
        "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
    }
    await websocket.send(json.dumps(msg))
    response = await websocket.recv()
    return response


async def change_margin_model(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    margin_model: str = "cross_pm",
) -> None:
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "private/change_margin_model",
        "params": {"margin_model": margin_model, "user_id": deribitUserCfg.user_id},
    }
    try:
        await websocket.send(json.dumps(msg))
        await websocket.recv()
    except Exception as e:
        raise Exception(f"change_margin_model wrong: {e}")


async def get_margins(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    amount: int,
    instrument_name: str,
    price: float,
) -> float:
    """
    获取初始保证金（BTC）。

    Args:
        price: 期权价格，标的单位（BTC / ETH）
    """
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "private/get_margins",
        "params": {
            "amount": amount,
            "instrument_name": instrument_name,
            "price": price,
        },
    }
    response = None
    response_result: dict[str, Any] | None = None
    try:
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        response_result = json.loads(response).get("result")
        initial_margin = float(response_result.get("buy"))
    except Exception as e:
        raise Exception(
            f"initial_margin wrong: {e}, {response_result}, {response}, {price}"
        )

    return initial_margin


async def get_testnet_initial_margin(
    deribitUserCfg: DeribitUserCfg, amount: int, instrument_name: str
) -> float:
    """
    在 Deribit 测试网环境下，根据 mid price 估算指定合约和张数的初始保证金 (BTC)。:contentReference[oaicite:5]{index=5}
    """
    async with websockets.connect(TEST_WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        await change_margin_model(websocket, deribitUserCfg)
        price = await get_mid_price_by_orderbook(
            websocket, deribitUserCfg, instrument_name
        )

        initial_margin = await get_margins(
            websocket, deribitUserCfg, amount, instrument_name, price
        )

        return initial_margin


async def get_interest_rate(
    deribitUserCfg: DeribitUserCfg, instrument_name: str
) -> float:
    """
    获取某个期权合约当前的利率估计。:contentReference[oaicite:6]{index=6}
    """
    async with websockets.connect(TEST_WS_URL) as websocket:
        msg = {
            "id": deribitUserCfg.user_id,
            "jsonrpc": "2.0",
            "method": "public/get_book_summary_by_instrument",
            "params": {"instrument_name": instrument_name},
        }
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        data = json.loads(response)
        result = data.get("result", [])
        if not result:
            raise ValueError(f"no result for instrument {instrument_name}")
        interest_rate = float(result[0].get("interest_rate"))
        return interest_rate


async def get_simulate_portfolio_initial_margin(
    deribitUserCfg: DeribitUserCfg, currency: str, simulated_positions: dict[str, int]
) -> float:
    """
    调用 Deribit 的 private/simulate_portfolio，返回模拟组合的初始保证金 (BTC)。:contentReference[oaicite:7]{index=7}
    """
    msg = {
        "id": deribitUserCfg.user_id,
        "jsonrpc": "2.0",
        "method": "private/simulate_portfolio",
        "params": {
            "add_positions": True,
            "currency": currency,
            "simulated_positions": simulated_positions,
        },
    }
    async with websockets.connect(TEST_WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        await change_margin_model(websocket, deribitUserCfg)
        await websocket.send(json.dumps(msg))
        response = await websocket.recv()
        data = json.loads(response)
        return float(data["result"]["initial_margin"])
