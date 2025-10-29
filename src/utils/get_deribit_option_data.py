from typing import Optional

import httpx


async def get_deribit_option_data(
    currency: str = "BTC",
    kind: str = "option",
    base_fee_btc: float = 0.0003,
    base_fee_eth: float = 0.0003,
    usdc_settled: bool = False,
    amount: float = 1.0,
    client: Optional[httpx.AsyncClient] = None,
):
    """拉取 Deribit 期权快照数据并提供更完整的盘口字段。

    返回的每个元素包含：
    - instrument_name
    - mark_iv
    - bid_price / ask_price / mark_price / last_price
    - underlying_price
    - strike / expiration
    - fee: 基于 Deribit 手续费上限规则的估算（以合约数量 * amount 为单位）
    """

    url = (
        "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        f"?currency={currency}&kind={kind}"
    )
    if client is not None:
        response = await client.get(url)
    else:
        async with httpx.AsyncClient(timeout=10.0) as local_client:
            response = await local_client.get(url)
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("result", []):
        option_name = item.get("instrument_name")
        mark_iv = float(item.get("mark_iv") or 0.0)
        bid_price = float(item.get("bid_price") or 0.0)
        ask_price = float(item.get("ask_price") or 0.0)
        mark_price = float(item.get("mark_price") or 0.0)
        last_price = float(item.get("last_price") or item.get("last") or 0.0)
        index_price = float(item.get("underlying_price") or 0.0)
        strike = float(item.get("strike") or 0.0)
        expiration = item.get("expiration") or item.get("expiration_timestamp")

        # 手续费估算：以 mark_price -> last_price -> (bid+ask)/2 的顺序选取参考价
        price_for_fee = mark_price or last_price or ((bid_price + ask_price) / 2.0)
        if price_for_fee <= 0:
            price_for_fee = max(bid_price, ask_price)

        if not usdc_settled:
            base_fee = base_fee_btc if currency == "BTC" else base_fee_eth
            fee = min(base_fee, 0.125 * price_for_fee) * amount
        else:
            fee = min(0.0003 * index_price, 0.125 * price_for_fee) * amount

        results.append(
            {
                "instrument_name": option_name,
                "mark_iv": mark_iv,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "mark_price": mark_price,
                "last_price": last_price,
                "underlying_price": index_price,
                "strike": strike,
                "expiration": expiration,
                "fee": fee,
            }
        )

    return results


# 示例调用
if __name__ == "__main__":
    import asyncio

    async def _demo():
        btc_options = await get_deribit_option_data(currency="BTC")
        for opt in btc_options[:5]:
            print(opt)

    asyncio.run(_demo())
