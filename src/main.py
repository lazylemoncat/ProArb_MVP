import csv
import time
import threading
from datetime import datetime

from utils.PolymarketAPI import PolymarketAPI
from utils.dataloader import load_manual_data
from utils.calculator import (
    bs_probability, 
    # calculate_margin, 
    calculate_pnl, 
    estimate_costs
)
from utils.DeribitStream import DeribitStream

OUTPUT_CSV = "data/results.csv"

# 全局实时行情存储
current_prices = {}  # { market_title: {spot, k1, k2} }
instruments_map = {}  # { market_title: {k1_inst, k2_inst} }


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


# --- 回调函数（DeribitStream 会持续调用） ---
def on_index(price):
    for market in current_prices.keys():
        current_prices[market]["spot"] = price


def on_option(inst, bid, ask):
    mid = (bid + ask) / 2 if bid and ask else None
    for market, insts in instruments_map.items():
        if inst == insts["k1"]:
            current_prices[market]["k1"] = mid
        elif inst == insts["k2"]:
            current_prices[market]["k2"] = mid


# --- 启动 Deribit 推流 ---
def start_deribit_stream():
    stream = DeribitStream(on_index_price=on_index, on_option_quote=on_option)
    thread = threading.Thread(target=stream.start, daemon=True)
    thread.start()


# --- 从 config 自动解析期权合约名称 ---
def resolve_instruments(events):
    print("🔍 正在查找 K1/K2 期权合约名称...")
    for m in events["events"]:
        title = m["polymarket"]["market_title"]
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]

        inst_k1 = DeribitStream.find_option_instrument(k1, call=True)
        inst_k2 = DeribitStream.find_option_instrument(k2, call=True)

        instruments_map[title] = {"k1": inst_k1, "k2": inst_k2}
        current_prices[title] = {"spot": None, "k1": None, "k2": None}

        print(f" ✅ {title}: K1={inst_k1}, K2={inst_k2}")

    print("✅ 合约解析完成\n")


# --- 主程序 ---
def main(config_path="config.yaml"):
    events = load_manual_data(config_path)

    resolve_instruments(events)
    start_deribit_stream()

    print("🚀 已启动 Deribit 实时行情流，并开始套利监控...\n")

    while True:
        for data in events["events"]:
            title = data["polymarket"]["market_title"]

            # Polymarket YES 实时价格
            event_id = PolymarketAPI.get_event_id_public_search(data['polymarket']['event_title'])
            market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
            poly_price = PolymarketAPI.get_yes_price(market_id)

            spot = current_prices[title]["spot"]
            k1_price = current_prices[title]["k1"]
            k2_price = current_prices[title]["k2"]

            if spot is None or k1_price is None or k2_price is None:
                print(f"⏳ [{title}] 等待 Deribit 行情数据...")
                continue

            k1 = data['deribit']['k1_strike']
            k2 = data['deribit']['k2_strike']
            investment = data['investment']

            volatility = 0.6
            time_to_expiry = 8 / 365
            rate = 0.05

            deribit_prob = bs_probability(spot, (k1 + k2) / 2, time_to_expiry, volatility, rate)
            # margin = calculate_margin(contract_size=1, risk_factor=0.02, premium=k1_price)
            costs = estimate_costs(investment)
            pnl = calculate_pnl(poly_price, deribit_prob, investment, costs)

            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            print(f"\n[{timestamp}] 🎯 {title}")
            print(f"YES={poly_price:.4f}  Spot={spot:.2f}  K1={k1_price:.5f}  K2={k2_price:.5f}")
            print(f"Deribit隐含概率={deribit_prob:.4f}   PnL={pnl:.2f}")

            save_result({
                "timestamp": timestamp,
                "market_title": title,
                "yes_price": poly_price,
                "spot": spot,
                "k1_mid": k1_price,
                "k2_mid": k2_price,
                "deribit_prob": deribit_prob,
                "expected_pnl": pnl,
                "suggest": "Strategy 1 ✅" if pnl > 20 else "No trade"
            })

        time.sleep(5)


if __name__ == "__main__":
    main()
