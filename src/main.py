import asyncio
import csv
import re
from datetime import datetime, timezone
from typing import Dict, Tuple

import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from strategy.cost_model import CostParams
from strategy.expected_value import EVInputs, expected_values_strategy1, expected_values_strategy2
from strategy.probability_engine import bs_probability_gt, interval_probabilities
from utils.PolymarketAPI import PolymarketAPI
from utils.dataloader import load_manual_data
from utils.deribit_api import get_spot_price, get_option_mid_price
from utils.DeribitStream import DeribitStream
from utils.get_polymarket_slippage import get_polymarket_slippage
from utils.get_deribit_option_data import get_deribit_option_data


# ==============================
# 全局常量
# ==============================
console = Console()


def parse_polymarket_strike(title: str) -> float:
    """从 Polymarket 市场标题中提取行权价（例如 "108,000" -> 108000）。"""
    if not title:
        return 0.0
    # 匹配形如 108,000 或 108000.00 的数值
    matches = re.findall(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?", title)
    if not matches:
        return 0.0
    candidate = matches[-1].replace(",", "")
    try:
        return float(candidate)
    except ValueError:
        return 0.0


def derive_option_prices(option_info: Dict[str, float]) -> Tuple[float, float, float]:
    """根据 Deribit 返回的盘口字段推导 bid/ask/mark 三个价格。"""
    bid = float(option_info.get("bid_price") or 0.0)
    ask = float(option_info.get("ask_price") or 0.0)
    mark = float(option_info.get("mark_price") or 0.0)
    last = float(option_info.get("last_price") or 0.0)

    if bid <= 0 and mark > 0:
        bid = mark
    if ask <= 0 and mark > 0:
        ask = mark
    if bid <= 0 and ask <= 0 and last > 0:
        bid = ask = last
    if bid <= 0 and ask > 0:
        bid = ask
    if ask <= 0 and bid > 0:
        ask = bid

    return bid, ask, mark or max(last, (bid + ask) / 2 if (bid + ask) > 0 else 0.0)


def format_probability(prob: float) -> str:
    return f"{prob * 100:.2f}%"


# ==============================
# 保存结果到 CSV
# ==============================
def save_result(row, output_csv_path: str):
    header = list(row.keys())
    try:
        with open(output_csv_path, "x", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)
    except FileExistsError:
        with open(output_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writerow(row)


# ==============================
# 主程序
# ==============================
async def main(config_path="config.yaml"):
    config_data = load_manual_data(config_path)
    events = config_data.get("events", [])
    investment_levels = config_data.get(
        "investment_levels", [1000, 5000, 10000, 20000, 50000]
    )
    output_csv_path = config_data.get("output_csv", "data/results.csv")
    thresholds = config_data.get("thresholds", {})
    check_interval = thresholds.get("check_interval_sec", 120)

    console.print(
        Panel.fit(
            "[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]",
            border_style="bright_cyan",
        )
    )

    async with httpx.AsyncClient(timeout=10.0) as polymarket_client:
        async with httpx.AsyncClient(timeout=10.0) as deribit_client:
            instruments_map: Dict[str, Dict[str, str | float]] = {}
            for m in events:
                title = m["polymarket"]["market_title"]
                k1 = m["deribit"]["k1_strike"]
                k2 = m["deribit"]["k2_strike"]

                inst_k1 = await DeribitStream.find_option_instrument(
                    k1, call=True, client=deribit_client
                )
                inst_k2 = await DeribitStream.find_option_instrument(
                    k2, call=True, client=deribit_client
                )

                poly_strike = parse_polymarket_strike(title)
                if poly_strike <= 0:
                    poly_strike = float(k1)

                instruments_map[title] = {
                    "k1": inst_k1,
                    "k2": inst_k2,
                    "poly_strike": poly_strike,
                }

                console.print(
                    f"✅ [green]{title}[/green]: {inst_k1}, {inst_k2} | Poly Strike ≈ {poly_strike}"
                )

            console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

            while True:
                for data in events:
                    try:
                        title = data["polymarket"]["market_title"]
                        event_id = await PolymarketAPI.get_event_id_public_search(
                            data["polymarket"]["event_title"], client=polymarket_client
                        )
                        market_id = await PolymarketAPI.get_market_id_by_market_title(
                            event_id, title, client=polymarket_client
                        )
                        market_data = await PolymarketAPI.get_market_by_id(
                            market_id, client=polymarket_client
                        )
                        outcome_prices = market_data.get("outcomePrices")

                        yes_price = no_price = 0.0
                        if outcome_prices:
                            try:
                                prices = (
                                    eval(outcome_prices)
                                    if isinstance(outcome_prices, str)
                                    else outcome_prices
                                )
                                yes_price, no_price = float(prices[0]), float(prices[1])
                            except Exception:
                                console.print("⚠️ [yellow]outcomePrices 格式异常[/yellow]")

                        spot = await get_spot_price(client=deribit_client)
                        k1_name = instruments_map[title]["k1"]
                        k2_name = instruments_map[title]["k2"]

                        deribit_list = await get_deribit_option_data(
                            currency="BTC", client=deribit_client
                        )
                        k1_info = next(
                            (d for d in deribit_list if d.get("instrument_name") == k1_name),
                            {},
                        )
                        k2_info = next(
                            (d for d in deribit_list if d.get("instrument_name") == k2_name),
                            {},
                        )

                        if not k1_info or not k2_info:
                            console.print(
                                f"⏳ [yellow]{title} 期权盘口暂时无报价，跳过[/yellow]"
                            )
                            continue

                        k1_bid, k1_ask, k1_mark = derive_option_prices(k1_info)
                        k2_bid, k2_ask, k2_mark = derive_option_prices(k2_info)
                        k1_mid = (
                            k1_mark
                            if k1_mark > 0
                            else await get_option_mid_price(k1_name, client=deribit_client)
                        )
                        k2_mid = (
                            k2_mark
                            if k2_mark > 0
                            else await get_option_mid_price(k2_name, client=deribit_client)
                        )
                        k1_mark_for_calc = k1_mark if k1_mark > 0 else (k1_mid or 0.0)
                        k2_mark_for_calc = k2_mark if k2_mark > 0 else (k2_mid or 0.0)

                        if not k1_mid or not k2_mid:
                            console.print(
                                f"⏳ [yellow]{title} 期权盘口缺少 mid 价格，跳过[/yellow]"
                            )
                            continue

                        k1_iv = float(k1_info.get("mark_iv") or 0.0)
                        k2_iv = float(k2_info.get("mark_iv") or 0.0)
                        k1_fee = float(k1_info.get("fee") or 0.0)
                        k2_fee = float(k2_info.get("fee") or 0.0)

                        _iv_pool = [v for v in (k1_iv, k2_iv) if v > 0]
                        mark_iv = sum(_iv_pool) / len(_iv_pool) if _iv_pool else 0.6
                        volatility = max(mark_iv, 1e-6)
                        deribit_fee = max(k1_fee, k2_fee)

                        k1_strike = float(data["deribit"]["k1_strike"])
                        k2_strike = float(data["deribit"]["k2_strike"])
                        poly_strike = float(
                            instruments_map[title].get("poly_strike") or 0.0
                        )
                        if poly_strike <= 0:
                            poly_strike = (k1_strike + k2_strike) / 2.0

                        time_to_expiry = 8 / 365
                        rate = 0.05
                        deribit_prob_yes = bs_probability_gt(
                            spot, poly_strike, time_to_expiry, volatility, rate
                        )
                        prob_segments = interval_probabilities(
                            spot,
                            k1_strike,
                            poly_strike,
                            k2_strike,
                            time_to_expiry,
                            volatility,
                            rate,
                        )
                        p_yes = prob_segments["Kp_to_K2"] + prob_segments["ge_K2"]
                        p_no = 1.0 - p_yes

                        tokens = await PolymarketAPI.get_clob_token_ids_by_market(
                            market_id, client=polymarket_client
                        )
                        yes_token_id = tokens["yes_token_id"]

                        timestamp = datetime.now(timezone.utc).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                        table = Table(
                            title=f"🎯 {title} | {timestamp}",
                            box=box.MINIMAL_DOUBLE_HEAD,
                            border_style="cyan",
                        )
                        table.add_column("指标", justify="left", style="bold")
                        table.add_column("数值", justify="right")

                        table.add_row("YES Price", f"{yes_price:.4f}")
                        table.add_row("NO Price", f"{no_price:.4f}")
                        table.add_row("Spot", f"{spot:.2f}")
                        table.add_row("K1/K2 Mid", f"{k1_mid:.5f} / {k2_mid:.5f}")
                        table.add_row("IV (K1/K2)", f"{k1_iv:.3f} / {k2_iv:.3f}")
                        table.add_row("Fee (K1/K2)", f"{k1_fee:.6f} / {k2_fee:.6f}")
                        table.add_row("Poly Strike", f"{poly_strike:.0f}")
                        table.add_row(
                            "Deribit Prob (Yes)", format_probability(deribit_prob_yes)
                        )
                        table.add_row(
                            "P(S_T < K1)", format_probability(prob_segments["lt_K1"])
                        )
                        table.add_row(
                            "P(K1 ≤ S_T < K_poly)",
                            format_probability(prob_segments["K1_to_Kp"]),
                        )
                        table.add_row(
                            "P(K_poly ≤ S_T < K2)",
                            format_probability(prob_segments["Kp_to_K2"]),
                        )
                        table.add_row(
                            "P(S_T ≥ K2)", format_probability(prob_segments["ge_K2"])
                        )

                        console.print(table)

                        for investment in investment_levels:
                            try:
                                result = await get_polymarket_slippage(
                                    yes_token_id, investment
                                )
                                slippage = float(result.get("slippage_pct", 0)) / 100
                            except Exception as e:
                                console.print(
                                    f"⚠️ [yellow]获取 Polymarket 滑点失败: {e}[/yellow]"
                                )
                                slippage = 0.01

                            ev_inputs = EVInputs(
                                S=spot,
                                K1=k1_strike,
                                K_poly=poly_strike,
                                K2=k2_strike,
                                T=time_to_expiry,
                                sigma=volatility,
                                r=rate,
                                poly_yes_price=yes_price,
                                call_k1_bid_btc=k1_bid,
                                call_k2_ask_btc=k2_ask,
                                call_k1_ask_btc=k1_ask,
                                call_k2_bid_btc=k2_bid,
                                call_k1_mark_btc=k1_mark_for_calc,
                                call_k2_mark_btc=k2_mark_for_calc,
                                btc_usd=spot,
                                inv_base_usd=investment,
                                slippage_rate_close=slippage,
                            )
                            cost_params = CostParams(risk_free_rate=rate)

                            try:
                                strategy1_ev = expected_values_strategy1(
                                    ev_inputs, cost_params
                                )
                            except ValueError as err:
                                console.print(
                                    f"⚠️ [yellow]策略一计算失败({err}), 跳过[/yellow]"
                                )
                                strategy1_ev = {
                                    "contracts_short": 0.0,
                                    "e_deribit": 0.0,
                                    "e_poly": 0.0,
                                    "open_cost": 0.0,
                                    "carry_cost": 0.0,
                                    "close_cost": 0.0,
                                    "total_cost": 0.0,
                                    "margin_requirement": 0.0,
                                    "total_ev": 0.0,
                                }

                            strategy2_ev = expected_values_strategy2(
                                ev_inputs, cost_params, poly_no_entry=no_price
                            )

                            suggest_s1 = "✅ 策略一" if strategy1_ev["total_ev"] > 0 else "-"
                            suggest_s2 = "✅ 策略二" if strategy2_ev["total_ev"] > 0 else "-"

                            console.print(
                                f"💼 投资 [cyan]{investment}[/cyan] → "
                                f"策略一EV={strategy1_ev['total_ev']:.2f} (Poly={strategy1_ev['e_poly']:.2f}, Deribit={strategy1_ev['e_deribit']:.2f}, Cost={strategy1_ev['total_cost']:.2f}) [{suggest_s1}] | "
                                f"策略二EV={strategy2_ev['total_ev']:.2f} (Poly={strategy2_ev['e_poly']:.2f}, Deribit={strategy2_ev['e_deribit']:.2f}, Cost={strategy2_ev['total_cost']:.2f}) [{suggest_s2}]"
                            )

                            save_result(
                                {
                                    "timestamp": timestamp,
                                    "market_title": title,
                                    "investment": investment,
                                    "spot": spot,
                                    "poly_yes_price": yes_price,
                                    "poly_no_price": no_price,
                                    "poly_strike": poly_strike,
                                    "k1_strike": k1_strike,
                                    "k2_strike": k2_strike,
                                    "deribit_prob_yes": deribit_prob_yes,
                                    "prob_lt_k1": prob_segments["lt_K1"],
                                    "prob_k1_to_kpoly": prob_segments["K1_to_Kp"],
                                    "prob_kpoly_to_k2": prob_segments["Kp_to_K2"],
                                    "prob_ge_k2": prob_segments["ge_K2"],
                                    "volatility_used": volatility,
                                    "mark_iv": mark_iv,
                                    "deribit_fee": deribit_fee,
                                    "polymarket_slippage": slippage,
                                    "strategy1_contracts": strategy1_ev["contracts_short"],
                                    "strategy1_ev": strategy1_ev["total_ev"],
                                    "strategy1_poly": strategy1_ev["e_poly"],
                                    "strategy1_deribit": strategy1_ev["e_deribit"],
                                    "strategy1_open_cost": strategy1_ev["open_cost"],
                                    "strategy1_carry_cost": strategy1_ev["carry_cost"],
                                    "strategy1_close_cost": strategy1_ev["close_cost"],
                                    "strategy1_total_cost": strategy1_ev["total_cost"],
                                    "strategy1_margin": strategy1_ev["margin_requirement"],
                                    "strategy2_contracts": strategy2_ev["contracts_long"],
                                    "strategy2_ev": strategy2_ev["total_ev"],
                                    "strategy2_poly": strategy2_ev["e_poly"],
                                    "strategy2_deribit": strategy2_ev["e_deribit"],
                                    "strategy2_open_cost": strategy2_ev["open_cost"],
                                    "strategy2_carry_cost": strategy2_ev["carry_cost"],
                                    "strategy2_close_cost": strategy2_ev["close_cost"],
                                    "strategy2_total_cost": strategy2_ev["total_cost"],
                                    "strategy2_margin": strategy2_ev["margin_requirement"],
                                    "p_yes": p_yes,
                                    "p_no": p_no,
                                    "k1_mid": k1_mid,
                                    "k2_mid": k2_mid,
                                    "k1_mark_iv": k1_iv,
                                    "k2_mark_iv": k2_iv,
                                    "k1_bid": k1_bid,
                                    "k1_ask": k1_ask,
                                    "k2_bid": k2_bid,
                                    "k2_ask": k2_ask,
                                    "direction": ", ".join(
                                        filter(lambda x: x != "-", [suggest_s1, suggest_s2])
                                    )
                                    or "观望",
                                },
                                output_csv_path,
                            )

                        console.rule("[bold magenta]Next Market[/bold magenta]")

                    except Exception as e:
                        console.print(
                            f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]"
                        )

                console.print(
                    f"\n[dim]⏳ 等待 {check_interval} 秒后重连 Deribit/Polymarket 数据流...[/dim]\n"
                )
                await asyncio.sleep(check_interval)


# ==============================
# 入口
# ==============================
if __name__ == "__main__":
    asyncio.run(main())
