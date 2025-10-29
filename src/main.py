import csv
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from utils.PolymarketAPI import PolymarketAPI
from utils.dataloader import load_manual_data
from utils.calculator import bs_probability, calculate_pnl, estimate_costs
from utils.deribit_api import get_spot_price, get_option_mid_price
from utils.DeribitStream import DeribitStream
from utils.get_polymarket_slippage import get_polymarket_slippage_sync
from utils.get_deribit_option_data import get_deribit_option_data


# ==============================
# 全局常量
# ==============================
OUTPUT_CSV = "data/results.csv"
INVESTMENTS = [1000, 5000, 10000, 20000, 50000]
console = Console()


# ==============================
# 保存结果到 CSV
# ==============================
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


# ==============================
# 主程序
# ==============================
def main(config_path="config.yaml"):
    events = load_manual_data(config_path)

    console.print(Panel.fit("[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]", border_style="bright_cyan"))

    # ✅ 解析 Deribit K1 / K2 合约
    instruments_map = {}
    for m in events["events"]:
        title = m["polymarket"]["market_title"]
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]

        inst_k1 = DeribitStream.find_option_instrument(k1, call=True)
        inst_k2 = DeribitStream.find_option_instrument(k2, call=True)
        instruments_map[title] = {"k1": inst_k1, "k2": inst_k2}

        console.print(f"✅ [green]{title}[/green]: {inst_k1}, {inst_k2}")

    console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

    while True:
        for data in events["events"]:
            try:
                title = data["polymarket"]["market_title"]

                # ✅ 获取 Polymarket YES / NO 实时价格
                event_id = PolymarketAPI.get_event_id_public_search(data['polymarket']['event_title'])
                market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
                market_data = PolymarketAPI.get_market_by_id(market_id)
                outcome_prices = market_data.get("outcomePrices")

                yes_price = no_price = 0
                if outcome_prices:
                    try:
                        prices = eval(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                        yes_price, no_price = float(prices[0]), float(prices[1])
                    except Exception:
                        console.print("⚠️ [yellow]outcomePrices 格式异常[/yellow]")

                # ✅ 获取 Deribit 现价 & 期权数据
                spot = get_spot_price()
                k1_mid = get_option_mid_price(instruments_map[title]["k1"])
                k2_mid = get_option_mid_price(instruments_map[title]["k2"])

                if k1_mid is None or k2_mid is None:
                    console.print(f"⏳ [yellow]{title} 期权盘口暂时无报价，跳过[/yellow]")
                    continue

                # === 批量拉取 Deribit 数据后筛选 K1/K2
                deribit_list = get_deribit_option_data(currency="BTC")
                k1_name = instruments_map[title]["k1"]
                k2_name = instruments_map[title]["k2"]

                k1_info = next((d for d in deribit_list if d.get("instrument_name") == k1_name), {})
                k2_info = next((d for d in deribit_list if d.get("instrument_name") == k2_name), {})

                k1_iv  = float(k1_info.get("mark_iv") or 0.0)
                k2_iv  = float(k2_info.get("mark_iv") or 0.0)
                k1_fee = float(k1_info.get("fee")     or 0.0)
                k2_fee = float(k2_info.get("fee")     or 0.0)

                # ✅ 统一定义 mark_iv（用于展示/记录），并用于后续 volatility
                _iv_pool = [v for v in (k1_iv, k2_iv) if v > 0]
                mark_iv = sum(_iv_pool) / len(_iv_pool) if _iv_pool else 0.6   # fallback

                volatility = mark_iv                  # ✅ 用 mark_iv 作为波动率
                deribit_fee = max(k1_fee, k2_fee)     # 保守取较大手续费

                # ✅ 概率计算
                k1_strike = data['deribit']['k1_strike']
                k2_strike = data['deribit']['k2_strike']
                time_to_expiry = 8 / 365
                rate = 0.05
                deribit_prob = bs_probability(spot, (k1_strike + k2_strike) / 2, time_to_expiry, volatility, rate)
                tokens = PolymarketAPI.get_clob_token_ids_by_market(market_id)
                yes_token_id = tokens["yes_token_id"]

                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # ✅ 输出表格
                table = Table(title=f"🎯 {title} | {timestamp}", box=box.MINIMAL_DOUBLE_HEAD, border_style="cyan")
                table.add_column("指标", justify="left", style="bold")
                table.add_column("数值", justify="right")

                table.add_row("YES Price", f"{yes_price:.4f}")
                table.add_row("NO Price", f"{no_price:.4f}")
                table.add_row("Spot", f"{spot:.2f}")
                table.add_row("K1/K2 Mid", f"{k1_mid:.5f} / {k2_mid:.5f}")
                table.add_row("IV (K1/K2)", f"{k1_iv:.3f} / {k2_iv:.3f}")
                table.add_row("Fee (K1/K2)", f"{k1_fee:.6f} / {k2_fee:.6f}")
                table.add_row("Vol Used", f"{volatility:.3f}")
                table.add_row("Deribit Prob", f"{deribit_prob:.4f}")

                console.print(table)

                # ✅ 多投资金额策略计算
                for investment in INVESTMENTS:
                    # ✅ Polymarket 滑点
                    try:
                        result = get_polymarket_slippage_sync(yes_token_id, investment)
                        slippage = float(result.get("slippage_pct", 0)) / 100
                    except Exception as e:
                        console.print(f"⚠️ [yellow]获取 Polymarket 滑点失败: {e}[/yellow]")
                        slippage = 0.01

                    costs = estimate_costs(investment, slippage=slippage, fee_rate=deribit_fee)
                    pnl_yes = calculate_pnl(yes_price, deribit_prob, investment, costs)
                    pnl_no = calculate_pnl(1 - no_price, 1 - deribit_prob, investment, costs)

                    suggest_yes = "✅ [green]ARBITRAGE[/green]" if pnl_yes > 0 else "[grey]No Trade[/grey]"
                    suggest_no = "✅ [green]ARBITRAGE[/green]" if pnl_no > 0 else "[grey]No Trade[/grey]"

                    console.print(f"💰 投资 [cyan]{investment}[/cyan] → YES_PnL={pnl_yes:.2f} {suggest_yes} | "
                                  f"NO_PnL={pnl_no:.2f} {suggest_no}")

                    save_result({
                        "timestamp": timestamp,
                        "market_title": title,
                        "investment": investment,
                        "spot": spot,
                        "poly_yes_price": yes_price,
                        "poly_no_price": no_price,
                        "deribit_prob": deribit_prob,
                        "volatility_used": volatility,
                        "mark_iv": mark_iv,
                        "deribit_fee": deribit_fee,
                        "polymarket_slippage": slippage,
                        "total_costs": costs,
                        "expected_pnl_yes": pnl_yes,
                        "expected_pnl_no": pnl_no,
                        "k1_mid": k1_mid,
                        "k2_mid": k2_mid,
                        "k1_mark_iv": k1_iv,
                        "k2_mark_iv": k2_iv,
                        "k1_fee": k1_fee,
                        "k2_fee": k2_fee,
                        "direction_yes": "Buy YES on Polymarket" if pnl_yes > 0 else "No Trade",
                        "direction_no": "Buy NO on Polymarket" if pnl_no > 0 else "No Trade"
                    })

                console.rule("[bold magenta]Next Market[/bold magenta]")

            except Exception as e:
                console.print(f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]")

        # ✅ 自动重连机制
        console.print("\n[dim]⏳ 等待 120 秒后重连 Deribit/Polymarket 数据流...[/dim]\n")
        time.sleep(120)


# ==============================
# 入口
# ==============================
if __name__ == "__main__":
    main()
