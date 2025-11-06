import asyncio
import json
import websockets
from typing import Literal

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def get_polymarket_slippage(
    asset_id: str, 
    amount: float, 
    side: Literal["buy", "sell"] = "buy", 
    amount_type: Literal["usd", "shares"] = "usd"
) -> dict[str, float | str]:
    """
    amount_type = "usd"（默认） → 保持原逻辑：花多少 USD 吃单
    amount_type = "shares"     → 新逻辑：卖（或买）多少份额，而不是多少美元
    """
    async with websockets.connect(WS_URL) as ws:
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
                    book = sorted(data.get("asks", []), key=lambda x: float(x["price"]))
                elif side == "sell":
                    book = sorted(data.get("bids", []), key=lambda x: float(x["price"]), reverse=True)
                else:
                    raise ValueError("side must be 'buy' or 'sell'")

                total_cost, total_size = 0.0, 0.0

                # ✅ 分岔点（核心逻辑）
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
                    if remaining_usd > 0:
                        pass
                        # raise ValueError(f"Insufficient liquidity for {amount} USD")

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
                    if remaining_shares > 0:
                        pass
                        # raise ValueError(f"Insufficient liquidity for {amount} shares")
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

                return {
                    "asset_id": asset_id,
                    "avg_price": round(avg_price, 6),
                    "shares_executed": round(total_size, 6),
                    "shares_bought": round(total_size, 6),
                    "total_cost_usd": round(total_cost, 6),
                    "slippage_pct": round(slippage_pct, 6),
                    "side": side,
                    "amount_type": amount_type
                }




# 同步封装，便于外部直接调用
def get_polymarket_slippage_sync(asset_id: str, amount_usd: float):
    return asyncio.run(get_polymarket_slippage(asset_id, amount_usd))


# 示例用法
if __name__ == "__main__":
    asset = "101465157040179639479168206247393302171925485943713651194544379689091809941131"
    for usd in [1000, 10000]:
        result = get_polymarket_slippage_sync(asset, usd)
        print(f"\n买入 ${usd:,}:")
        print(result)
