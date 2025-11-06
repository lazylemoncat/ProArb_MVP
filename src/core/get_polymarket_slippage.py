import asyncio
import json
import websockets

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def get_polymarket_slippage(asset_id: str, amount_usd: float, side: str = "buy") -> dict[str, float | str]:
    """
    计算买入或卖出指定 USD 金额时的滑点（支持 asks / bids）
    side="buy" 表示吃 asks（买入）  
    side="sell" 表示吃 bids（卖出）
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
                if side == "buy":   # === 买入吃 asks ===
                    book = data.get("asks", [])
                    if not book:
                        raise ValueError("No asks available")
                    book = sorted(book, key=lambda x: float(x["price"]))  # 升序
                elif side == "sell":  # === 卖出吃 bids ===
                    book = data.get("bids", [])
                    if not book:
                        raise ValueError("No bids available")
                    book = sorted(book, key=lambda x: float(x["price"]), reverse=True)
                else:
                    raise ValueError("side must be 'buy' or 'sell'")

                total_cost, total_size = 0.0, 0.0
                remaining = amount_usd

                for level in book:
                    price = float(level["price"])
                    size = float(level["size"])
                    level_value = price * size

                    if remaining > level_value:
                        total_cost += level_value
                        total_size += size
                        remaining -= level_value
                    else:
                        total_cost += remaining
                        total_size += remaining / price
                        remaining = 0
                        break

                if total_size == 0:
                    raise ValueError("Insufficient liquidity to execute order")

                avg_price = total_cost / total_size
                best_price = float(book[0]["price"])

                if side == "buy":
                    slippage_pct = (avg_price - best_price) / best_price * 100
                else:
                    slippage_pct = (best_price - avg_price) / best_price * 100

                return {
                    "asset_id": asset_id,
                    "avg_price": round(avg_price, 6),
                    "shares_bought": round(total_size, 6),
                    "slippage_pct": round(slippage_pct, 6),
                    "side": side
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
