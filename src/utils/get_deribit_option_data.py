import requests

def get_deribit_option_data(
    currency="BTC", 
    kind="option", 
    base_fee_btc=0.0003, 
    base_fee_eth=0.0003, 
    usdc_settled=False, 
    amount=1
):
    """
    获取 Deribit 期权数据并计算 mark_iv 和手续费。
    """
    
    url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={currency}&kind={kind}"
    response = requests.get(url)
    data = response.json()
    
    results = []
    for item in data.get("result", []):
        option_name = item.get("instrument_name")
        mark_iv = item.get("mark_iv", None)
        option_price = item.get("last") or 0.0  # 防止 None 报错
        index_price = item.get("underlying_price") or 0.0

        # 计算手续费
        if not usdc_settled:
            base_fee = base_fee_btc if currency == "BTC" else base_fee_eth
            fee = min(base_fee, 0.125 * option_price) * amount
        else:
            fee = min(0.0003 * index_price, 0.125 * option_price) * amount
        
        results.append({
            "instrument_name": option_name,
            "mark_iv": mark_iv,
            "fee": fee
        })
    
    return results


# 示例调用
if __name__ == "__main__":
    btc_options = get_deribit_option_data(currency="BTC")
    for opt in btc_options[:5]:
        print(opt)
