import asyncio
import json
import websockets

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def get_polymarket_slippage(asset_id: str, amount_usd: float) -> dict[str, float | str]:
    """
    获取指定 asset_id 的订单簿并计算买入给定金额的滑点
    :param asset_id: Polymarket CLOB asset id
    :param amount_usd: 买入金额（美元）
    :return: dict(avg_price, shares_bought, slippage_pct)
    """

    async with websockets.connect(WS_URL) as ws:
        # 订阅单个 asset_id 的市场数据
        sub_msg = {"assets_ids": [asset_id], "type": "market"}
        await ws.send(json.dumps(sub_msg))

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            # 如果是列表，取第一个元素
            if isinstance(data, list):
                data = data[0]

            # 找到订单簿数据
            if data.get("event_type") == "book" and data.get("asset_id") == asset_id:
                asks = data.get("asks", [])
                if not asks:
                    return {"error": "No asks available"}

                # 确保 asks 按价格升序排序
                asks = sorted(asks, key=lambda x: float(x["price"]))

                # === 计算滑点 ===
                total_cost = 0.0
                total_size = 0.0
                remaining = amount_usd

                for level in asks:
                    price = float(level["price"])
                    size = float(level["size"])
                    level_value = price * size

                    if remaining > level_value:
                        total_cost += level_value
                        total_size += size
                        remaining -= level_value
                    else:
                        partial_size = remaining / price
                        total_cost += remaining
                        total_size += partial_size
                        remaining = 0
                        break

                if total_size == 0:
                    return {"error": "Insufficient liquidity"}

                avg_price = total_cost / total_size
                best_price = float(asks[0]["price"])
                slippage_pct = (avg_price - best_price) / best_price * 100

                return {
                    "asset_id": asset_id,
                    "avg_price": round(avg_price, 6),
                    "shares_bought": round(total_size, 6),
                    "slippage_pct": round(slippage_pct, 6),
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
