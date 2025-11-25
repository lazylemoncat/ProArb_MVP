from dataclasses import dataclass
import json
from typing import Literal

import websockets

from .polymarket_ws import PolymarketWS


@dataclass
class Polymarket_Slippage:
    asset_id: str
    avg_price: float
    shares: float
    total_cost_usd: float
    slippage_pct: float
    side: Literal["buy", "sell"]
    amount_type: Literal["usd", "shares"]

def _simulate_fill(
    book: list[tuple[float, float]],
    amount: float,
    side: Literal["buy", "sell"],
    amount_type: Literal["usd", "shares"],
) -> tuple[float, float, float, float]:
    """
    只在"能完整吃下 amount"的情况下计算滑点
    在给定 orderbook 上模拟吃单，返回:
        (avg_price, total_size, total_cost, slippage_pct)
    如果订单簿深度不足以完全吃下给定 amount, 则抛出 ValueError.
    """
    if amount_type not in ("usd", "shares"):
        raise ValueError("amount_type must be 'usd' or 'shares'")
    if not book:
        raise ValueError("Empty orderbook")

    best_price = book[0][0]
    total_cost = 0.0
    total_size = 0.0

    if amount_type == "usd":
        remaining_value = amount
        for price, size in book:
            if remaining_value <= 0:
                break

            level_value = price * size
            if remaining_value >= level_value:
                # 吃完整一档
                total_cost += level_value
                total_size += size
                remaining_value -= level_value
            else:
                # 吃部分这一档
                partial_size = remaining_value / price
                total_cost += remaining_value
                total_size += partial_size
                remaining_value = 0.0
                break

        # 如果还有剩余金额，说明订单簿深度不够，无法“完整吃下”
        if remaining_value > 1e-9:
            raise ValueError("Insufficient liquidity to fully execute given USD amount")

    else:  # amount_type == "shares"
        remaining_shares = amount
        for price, size in book:
            if remaining_shares <= 0:
                break

            if remaining_shares >= size:
                # 吃完整一档
                total_cost += price * size
                total_size += size
                remaining_shares -= size
            else:
                # 吃部分这一档
                total_cost += price * remaining_shares
                total_size += remaining_shares
                remaining_shares = 0.0
                break

        # 如果还有剩余份额，说明订单簿深度不够，无法“完整吃下”
        if remaining_shares > 1e-9:
            raise ValueError("Insufficient liquidity to fully execute given shares amount")

    if total_size == 0:
        # 理论上如果 amount > 0 且上面检查通过，不会走到这
        raise ValueError("Insufficient liquidity to execute any size")

    avg_price = total_cost / total_size
    if side == "buy":
        slippage_pct = (avg_price - best_price) / best_price * 100
    else:
        slippage_pct = (best_price - avg_price) / best_price * 100

    return avg_price, total_size, total_cost, slippage_pct


async def get_polymarket_slippage(
    asset_id: str,
    amount: float,
    side: Literal["buy", "sell"] = "buy",
    amount_type: Literal["usd", "shares"] = "usd",
) -> Polymarket_Slippage:
    """
    基于当前 orderbook 估算 Polymarket 交易的滑点。

    amount_type = "usd"(默认) → 花多少 USD 吃单(必须能完全吃完这笔 USD)
    amount_type = "shares"     → 买/卖多少份额（必须能完全成交这些份额）

    如果订单簿深度不足以完全吃下给定 amount, 则抛出 ValueError。
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    book = await PolymarketWS.fetch_orderbook(
        asset_id=asset_id,
        side=side,
    )

    avg_price, total_size, total_cost, slippage_pct = _simulate_fill(
        book=book,
        amount=amount,
        side=side,
        amount_type=amount_type,
    )

    return Polymarket_Slippage(
        asset_id = asset_id,
        avg_price = round(avg_price, 6),
        shares = round(total_size, 6),
        total_cost_usd = round(total_cost, 6),
        slippage_pct = round(slippage_pct, 6),
        side = side,
        amount_type = amount_type,
    )

async def get_polymarket_slippage_(
    asset_id: str,
    amount: float,
    side: Literal["buy", "sell"] = "buy",
    amount_type: Literal["usd", "shares"] = "usd",
) -> Polymarket_Slippage:
    """
    基于当前 orderbook 估算 Polymarket 交易的滑点。:contentReference[oaicite:9]{index=9}

    amount_type = "usd"（默认） → 花多少 USD 吃单
    amount_type = "shares"     → 买/卖多少份额，而不是多少美元
    """
    CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    async with websockets.connect(CLOB_WS_URL) as ws:
        await ws.send(json.dumps({"assets_ids": [asset_id], "type": "market"}))

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            if isinstance(data, list):
                if len(data) == 0:
                    raise ValueError("Empty websocket data from Polymarket")
                data = data[0]

            if data.get("event_type") == "book" and data.get("asset_id") == asset_id:
                if side == "buy":
                    book = sorted(
                        data.get("asks", []), key=lambda x: float(x["price"])
                    )
                elif side == "sell":
                    book = sorted(
                        data.get("bids", []),
                        key=lambda x: float(x["price"]),
                        reverse=True,
                    )
                else:
                    raise ValueError("side must be 'buy' or 'sell'")

                total_cost, total_size = 0.0, 0.0

                # 按 USD 或 shares 计算吃单
                if amount_type == "usd":
                    remaining_usd = amount
                    for lvl in book:
                        price = float(lvl["price"])
                        size = float(lvl["size"])
                        level_value = price * size

                        if remaining_usd >= level_value:
                            total_cost += level_value
                            total_size += size
                            remaining_usd -= level_value
                        else:
                            total_cost += remaining_usd
                            total_size += remaining_usd / price
                            remaining_usd = 0
                            break

                elif amount_type == "shares":
                    remaining_shares = amount
                    for lvl in book:
                        price = float(lvl["price"])
                        size = float(lvl["size"])

                        if remaining_shares >= size:
                            total_cost += size * price
                            total_size += size
                            remaining_shares -= size
                        else:
                            total_cost += remaining_shares * price
                            total_size += remaining_shares
                            remaining_shares = 0
                            break

                else:
                    raise ValueError("amount_type must be 'usd' or 'shares'")

                if total_size == 0:
                    raise ValueError("Insufficient liquidity")

                avg_price = total_cost / total_size
                best_price = float(book[0]["price"])
                if side == "buy":
                    slippage_pct = (avg_price - best_price) / best_price * 100
                else:
                    slippage_pct = (best_price - avg_price) / best_price * 100

                return Polymarket_Slippage(
                    asset_id=asset_id,
                    avg_price=round(avg_price, 6),
                    shares=round(total_size, 6),
                    total_cost_usd=round(total_cost, 6),
                    slippage_pct=round(slippage_pct, 6),
                    side=side,
                    amount_type=amount_type
                )
