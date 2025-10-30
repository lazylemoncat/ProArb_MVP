import time
from datetime import datetime, timezone

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.deribit_api import get_spot_price
from core.DeribitStream import DeribitStream
from core.get_deribit_option_data import get_deribit_option_data
from core.get_polymarket_slippage import get_polymarket_slippage_sync
from core.PolymarketAPI import PolymarketAPI
from models.result_record import ResultRecord
from strategy.cost_models import CostParams
from strategy.expected_value import (
    EVInputs,
    expected_values_strategy1,
    expected_values_strategy2,
)
from strategy.probability_engine import bs_probability_gt  # 用统一的N(d2)
from utils.dataloader import load_manual_data
from utils.save_result import save_result_csv

console = Console()


def main(config_path="config.yaml"):
    config = load_manual_data(config_path)
    OUTPUT_CSV = config["thresholds"]["OUTPUT_CSV"]
    INVESTMENTS = config["thresholds"]["INVESTMENTS"]
    IM = config["thresholds"]["MARGIN_USD"]  # 初始保证金从配置读取

    params = CostParams()
    events = config["events"]
    instruments_map = {}

    console.print(
        Panel.fit("[bold cyan]Deribit x Polymarket Arbitrage EV Monitor[/bold cyan]", border_style="bright_cyan")
    )

    # 解析每个事件的 Deribit 合约
    for m in events:
        title = m["polymarket"]["market_title"]
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]
        inst_k1 = DeribitStream.find_option_instrument(k1, call=True)
        inst_k2 = DeribitStream.find_option_instrument(k2, call=True)
        instruments_map[title] = {"k1": inst_k1, "k2": inst_k2}
        console.print(f"✅ [green]{title}[/green]: {inst_k1}, {inst_k2}")

    console.print("\n🚀 [bold yellow]开始实时套利监控（双策略）...[/bold yellow]\n")

    while True:
        for data in events:
            try:
                title = data["polymarket"]["market_title"]

                # === Polymarket 数据 ===
                event_id = PolymarketAPI.get_event_id_public_search(data["polymarket"]["event_title"])
                market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
                market_data = PolymarketAPI.get_market_by_id(market_id)
                outcome_prices = market_data.get("outcomePrices")

                yes_price = no_price = 0.0
                if outcome_prices:
                    try:
                        prices = eval(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                        yes_price, no_price = float(prices[0]), float(prices[1])
                    except Exception:
                        console.print("⚠️ [yellow]outcomePrices 格式异常[/yellow]")

                # === Deribit 行情（含 bid/ask） ===
                spot = get_spot_price()
                deribit_list = get_deribit_option_data(currency="BTC")
                k1_strike = data["deribit"]["k1_strike"]
                k2_strike = data["deribit"]["k2_strike"]
                k1_name = instruments_map[title]["k1"]
                k2_name = instruments_map[title]["k2"]

                k1_info = next((d for d in deribit_list if d.get("instrument_name") == k1_name), {})
                k2_info = next((d for d in deribit_list if d.get("instrument_name") == k2_name), {})

                k1_iv  = float(k1_info.get("mark_iv") or 0.0)
                k2_iv  = float(k2_info.get("mark_iv") or 0.0)
                k1_bid = float(k1_info.get("bid_price") or 0.0)
                k1_ask = float(k1_info.get("ask_price") or 0.0)
                k2_bid = float(k2_info.get("bid_price") or 0.0)
                k2_ask = float(k2_info.get("ask_price") or 0.0)

                _iv_pool = [v for v in (k1_iv, k2_iv) if v > 0]
                volatility = sum(_iv_pool) / len(_iv_pool) if _iv_pool else 0.6

                K_poly = (k1_strike + k2_strike) / 2  # 近似
                T_years = 8 / 365
                rate = params.risk_free_rate

                # 统一的 Deribit 概率（用于报表对齐）
                deribit_prob = bs_probability_gt(S=spot, K=K_poly, T=T_years, sigma=volatility, r=rate)

                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # === 行情概览 ===
                table = Table(title=f"🎯 {title} | {timestamp}", box=box.MINIMAL_DOUBLE_HEAD, border_style="cyan")
                table.add_column("指标", justify="left", style="bold")
                table.add_column("数值", justify="right")
                table.add_row("Spot", f"{spot:.2f}")
                table.add_row("YES Price", f"{yes_price:.4f}")
                table.add_row("NO Price", f"{no_price:.4f}")
                table.add_row("Deribit Prob", f"{deribit_prob:.4f}")
                table.add_row("Vol Used", f"{volatility:.3f}")
                console.print(table)

                # === 投资额循环 ===
                for investment in INVESTMENTS:
                    # 滑点（YES 侧，用于两策略的收盘成本近似）
                    try:
                        yes_token_id = PolymarketAPI.get_clob_token_ids_by_market(market_id)["yes_token_id"]
                        slip_res = get_polymarket_slippage_sync(yes_token_id, investment)
                        slippage = float(slip_res.get("slippage_pct", 0)) / 100
                    except Exception as e:
                        console.print(f"⚠️ 获取 Polymarket 滑点失败: {e}")
                        slippage = 0.01

                    # === 策略一：做多YES + 做空Deribit垂直价差 ===
                    ev_in_yes = EVInputs(
                        S=spot, K1=k1_strike, K_poly=K_poly, K2=k2_strike,
                        T=T_years, sigma=volatility, r=rate,
                        poly_yes_price=yes_price,
                        call_k1_bid_btc=k1_bid, call_k1_ask_btc=k1_ask,
                        call_k2_bid_btc=k2_bid, call_k2_ask_btc=k2_ask,
                        btc_usd=spot, inv_base_usd=investment,
                        margin_requirement_usd=IM, slippage_rate_close=slippage,
                    )
                    ev_yes_out = expected_values_strategy1(ev_in_yes, params)
                    ev_yes = float(ev_yes_out["total_ev"])
                    total_cost_yes = float(ev_yes_out.get("total_cost", 0.0))

                    # === 策略二：做空YES(做多NO) + 做多Deribit垂直价差 ===
                    ev_in_no = EVInputs(
                        S=spot, K1=k1_strike, K_poly=K_poly, K2=k2_strike,
                        T=T_years, sigma=volatility, r=rate,
                        poly_yes_price=yes_price,
                        call_k1_bid_btc=k1_bid, call_k1_ask_btc=k1_ask,
                        call_k2_bid_btc=k2_bid, call_k2_ask_btc=k2_ask,
                        btc_usd=spot, inv_base_usd=investment,
                        margin_requirement_usd=IM, slippage_rate_close=slippage,
                    )
                    ev_no_out = expected_values_strategy2(ev_in_no, params, poly_no_entry=no_price)
                    ev_no = float(ev_no_out["total_ev"])
                    # 你也可以选择 separate total_cost_no；PRD仅需一个 total_costs，这里用YES侧对齐 expected_pnl_yes
                    total_costs = total_cost_yes

                    # 期望收益（按PRD命名：expected_pnl_yes 用策略一）
                    expected_pnl_yes = ev_yes
                    EV_best = max(ev_yes, ev_no)
                    EV_IM_ratio = (EV_best / IM) if IM > 0 else 0.0

                    # === 统一结果模型 ===
                    row = ResultRecord(
                        market_title=title,
                        timestamp=timestamp,
                        investment=investment,
                        spot=spot,
                        poly_yes_price=yes_price,
                        deribit_prob=deribit_prob,
                        expected_pnl_yes=expected_pnl_yes,
                        total_costs=total_costs,
                        EV=EV_best,
                        IM=IM,
                        EV_IM_ratio=EV_IM_ratio,
                        ev_yes=ev_yes,
                        ev_no=ev_no,
                    )

                    # 控制台输出
                    suggest1 = "✅ YES" if ev_yes > 0 else "—"
                    suggest2 = "✅ NO"  if ev_no  > 0 else "—"
                    console.print(
                        f"💰 {investment:.0f} | EV_yes={ev_yes:.2f} {suggest1} | "
                        f"EV_no={ev_no:.2f} {suggest2} | EV*={EV_best:.2f} | EV/IM={EV_IM_ratio:.3f}"
                    )

                    # 保存（严格按模型字段）
                    save_result_csv(row.to_dict(), OUTPUT_CSV)

                console.rule("[bold magenta]Next Market[/bold magenta]")

            except Exception as e:
                console.print(f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]")

        check_interval_sec = config["thresholds"]["check_interval_sec"]
        console.print(f"\n[dim]⏳ 等待 {check_interval_sec} 秒后重连数据流...[/dim]\n")
        time.sleep(check_interval_sec)


if __name__ == "__main__":
    main()
