import csv
import time
from datetime import datetime, timezone

from utils.PolymarketAPI import PolymarketAPI
from utils.dataloader import load_manual_data
from utils.calculator import (
    bs_probability, 
    # calculate_margin, 
    calculate_pnl, 
    estimate_costs
)
from utils.deribit_api import get_spot_price, get_option_mid_price
from utils.DeribitStream import DeribitStream   # 仅用于 find_option_instrument


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
    events = load_manual_data(config_path)

    # ✅ 解析 K1/K2 合约名称
    instruments_map = {}
    for m in events["events"]:
        title = m["polymarket"]["market_title"]
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]

        inst_k1 = DeribitStream.find_option_instrument(k1, call=True)
        inst_k2 = DeribitStream.find_option_instrument(k2, call=True)

        instruments_map[title] = {"k1": inst_k1, "k2": inst_k2}

        print(f"✅ {title}: {inst_k1}, {inst_k2}")

    print("\n🚀 开始实时套利监控...\n")

    while True:
        for data in events["events"]:
            title = data["polymarket"]["market_title"]
            try:
                # Polymarket YES 实时价格
                event_id = PolymarketAPI.get_event_id_public_search(data['polymarket']['event_title'])
                market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
                poly_price = PolymarketAPI.get_yes_price(market_id)

                # ✅ Deribit 实时 API 拉取
                spot = get_spot_price()
                k1_mid = get_option_mid_price(instruments_map[title]["k1"])
                k2_mid = get_option_mid_price(instruments_map[title]["k2"])
            except Exception as e:
                print(f"⚠️ 数据获取失败，跳过此次循环: {e}")
                continue

            if k1_mid is None or k2_mid is None:
                print(f"⏳ {title} 期权盘口暂时无报价，跳过")
                continue

            k1 = data['deribit']['k1_strike']
            k2 = data['deribit']['k2_strike']
            investment = data['investment']

            volatility = 0.6
            time_to_expiry = 8 / 365
            rate = 0.05

            deribit_prob = bs_probability(spot, (k1 + k2) / 2, time_to_expiry, volatility, rate)
            # margin = calculate_margin(contract_size=1, risk_factor=0.02, premium=k1_mid)
            costs = estimate_costs(investment)
            pnl = calculate_pnl(poly_price, deribit_prob, investment, costs)

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            print(f"\n[{timestamp}] 🎯 {title}")
            print(f"YES={poly_price:.4f} | Spot={spot:.2f} | K1_mid={k1_mid:.5f} | K2_mid={k2_mid:.5f}")
            print(f"Deribit隐含={deribit_prob:.4f} | PnL={pnl:.2f}")

            save_result({
                "timestamp": timestamp,
                "market_title": title,
                "yes_price": poly_price,
                "spot": spot,
                "k1_mid": k1_mid,
                "k2_mid": k2_mid,
                "deribit_prob": deribit_prob,
                "expected_pnl": pnl,
                "spread": poly_price - deribit_prob,         # ✅ 概率价差
                "suggest": "✅ ARBITRAGE" if pnl > 0 else "No Trade",   # ✅ 套利信号
            })

        time.sleep(120)


if __name__ == "__main__":
    main()
