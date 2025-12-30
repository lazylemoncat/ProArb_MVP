from dataclasses import dataclass
from typing import Literal, Optional

from .polymarket_ws import PolymarketWS


@dataclass
class Polymarket_Slippage:
    asset_id: str
    avg_price: float
    # 实际成交份额（兼容老代码的 .shares 写法）
    shares: float
    total_cost_usd: float
    slippage_pct: float
    side: Literal["ask", "bid"]
    amount_type: Literal["usd", "shares"]
    # === 新增：盘口信息，用于套利分析 ===
    best_ask: Optional[float] = None
    best_bid: Optional[float] = None
    mid_price: Optional[float] = None
    spread: Optional[float] = None

class Insufficient_liquidity(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

def _simulate_fill(
    book: list[tuple[float, float]],
    amount: float,
    side: Literal["ask", "bid"],
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
            raise Insufficient_liquidity("Insufficient liquidity to fully execute given shares amount")

    if total_size == 0:
        # 理论上如果 amount > 0 且上面检查通过，不会走到这
        raise Insufficient_liquidity("Insufficient liquidity to execute any size")

    avg_price = total_cost / total_size
    if side == "ask":
        slippage_pct = (avg_price - best_price) / best_price * 100
    else:
        slippage_pct = (best_price - avg_price) / best_price * 100

    return avg_price, total_size, total_cost, slippage_pct


async def get_polymarket_slippage(
    asset_id: str,
    amount: float,
    side: Literal["ask", "bid"] = "ask",
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

    # 先获取当前方向的盘口，用于模拟吃单
    book = await PolymarketWS.fetch_orderbook(
        asset_id=asset_id,
        side=side,
    )

    try:
        avg_price, total_size, total_cost, slippage_pct = _simulate_fill(
            book=book,
            amount=amount,
            side=side,
            amount_type=amount_type,
        )
    except Insufficient_liquidity as e:
        raise Insufficient_liquidity(e)

    # === 额外获取盘口信息（best_ask / best_bid / mid / spread）===
    # 当前方向最佳价
    best_side_price = book[0][0] if book else None

    # 反方向盘口（只需要最优一档）
    other_side = "bid" if side == "ask" else "ask"
    try:
        other_book = await PolymarketWS.fetch_orderbook(
            asset_id=asset_id,
            side=other_side,
        )
    except Exception:
        other_book = []

    other_side_price = other_book[0][0] if other_book else None

    if side == "ask":
        best_ask = best_side_price
        best_bid = other_side_price
    else:
        best_bid = best_side_price
        best_ask = other_side_price

    if best_ask is not None and best_bid is not None:
        mid_price = (best_ask + best_bid) / 2.0
        spread = best_ask - best_bid
    else:
        mid_price = None
        spread = None

    return Polymarket_Slippage(
        asset_id=asset_id,
        avg_price=round(avg_price, 6),
        shares=round(total_size, 6),
        total_cost_usd=round(total_cost, 6),
        slippage_pct=round(slippage_pct, 6),
        side=side,
        amount_type=amount_type,
        best_ask=best_ask,
        best_bid=best_bid,
        mid_price=mid_price,
        spread=spread,
    )