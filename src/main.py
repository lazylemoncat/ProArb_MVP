import csv
from utils.dataloader import load_manual_data
from utils.calculator import (
    bs_probability,
    calculate_margin,
    calculate_pnl,
    estimate_costs
)

OUTPUT_CSV = "data/results.csv"

def save_result(row):
    header = list(row.keys())
    try:
        with open(OUTPUT_CSV, "x", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)
    except FileExistsError:
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writerow(row)


def main(config_path="config.yaml"):
    markets = load_manual_data(config_path)  # :contentReference[oaicite:1]{index=1}
    
    for data in markets["markets"]:

        poly_price = data['polymarket']['yes_price']      # ← 需 API 获取
        spot = data['deribit']['spot_price']              # ← 需 API 获取
        k1 = data['deribit']['k1_strike']
        k2 = data['deribit']['k2_strike']
        k1_price = data['deribit']['k1_option_price']     # ← 需 API 获取
        # k2_price = data['deribit']['k2_option_price']   # ← 需 API 获取
        investment = data['investment']

        volatility = 0.6
        time = 8 / 365
        rate = 0.05

        deribit_prob = bs_probability(spot, (k1 + k2) / 2, time, volatility, rate)  # :contentReference[oaicite:2]{index=2}
        margin = calculate_margin(contract_size=1, risk_factor=0.02, premium=k1_price)
        costs = estimate_costs(investment)
        pnl = calculate_pnl(poly_price, deribit_prob, investment, costs)

        # === 打印 ===
        print("\n=== 套利机会分析 ===")
        print(f"市场: {data['polymarket']['market_id']}")
        print(f"Polymarket概率: {poly_price * 100:.2f}%")
        print(f"Deribit隐含概率: {deribit_prob * 100:.2f}%")
        print(f"价差: {(poly_price - deribit_prob) * 100:.2f}%")
        print(f"保证金需求: ${margin:.2f}")
        print(f"预估成本: ${costs:.2f}")
        print(f"预期收益: ${pnl:.2f}")

        # === 保存结果 ===
        save_result({
            "market_id": data['polymarket']['market_id'],
            "poly_yes_price": poly_price,
            "spot": spot,
            "k1": k1,
            "k2": k2,
            "k1_option_price": k1_price,
            "investment": investment,
            "deribit_prob": deribit_prob,
            "ev_spread": poly_price - deribit_prob,
            "expected_pnl": pnl,
            "suggest": "Strategy 1" if pnl > 20 else "No trade"
        })

if __name__ == "__main__":
    main()
