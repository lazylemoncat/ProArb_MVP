# ================= main.py =================
from utils.dataloader import load_manual_data
from utils.calculator import (
    bs_probability,
    calculate_margin,
    calculate_pnl,
    estimate_costs
)

def main(config_path="config.yaml"):
    data = load_manual_data(config_path)


    poly_price = data['polymarket']['yes_price']
    spot = data['deribit']['spot_price']
    k1 = data['deribit']['k1_strike']
    k2 = data['deribit']['k2_strike']
    p1 = data['deribit']['k1_option_price']
    p2 = data['deribit']['k2_option_price']
    investment = data['investment']


    # 假设参数
    volatility = 0.6
    time = 8/365
    rate = 0.05


    deribit_prob = bs_probability(spot, (k1 + k2) / 2, time, volatility, rate)
    margin = calculate_margin(contract_size=1, risk_factor=0.02, premium=p1)
    costs = estimate_costs(investment)
    pnl = calculate_pnl(poly_price, deribit_prob, investment, costs)


    print("=== 套利机会分析 ===")
    print(f"市场: {data['polymarket']['market_id']}")
    print(f"Polymarket概率: {poly_price * 100:.2f}%")
    print(f"Deribit隐含概率: {deribit_prob * 100:.2f}%")
    print(f"价差: {(poly_price - deribit_prob) * 100:.2f}%")
    print(f"保证金需求: ${margin:.2f}")
    print(f"预估成本: ${costs:.2f}")
    print(f"预期收益: ${pnl:.2f}")


    if pnl > 20:
        print("建议: 存在套利机会，推荐执行策略一")
    else:
        print("建议: 无显著套利空间")


if __name__ == "__main__":
    main()