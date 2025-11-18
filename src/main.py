import asyncio
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.deribit_api import (
    calc_slippage,
    get_orderbook,
    get_spot_price,
    get_testnet_initial_margin,
    DeribitUserCfg
)
from core.get_deribit_option_data import get_deribit_option_data
from core.get_polymarket_slippage import get_polymarket_slippage
from core.PolymarketAPI import PolymarketAPI

from strategy.position_calculator import (
    PositionInputs,
    strategy1_position_contracts,
    strategy2_position_contracts,
)

from strategy.probability_engine import bs_probability_gt
from utils.dataloader import load_manual_data
from utils.init_markets import init_markets
from utils.save_result import save_result_csv

from strategy.test_fixed import main_calculation, CalculationInput, PMEParams

console = Console()
load_dotenv()


async def loop_event(
    data,
    deribitUserCfg: DeribitUserCfg,
    investments,
    output_csv,
    instruments_map
):
    title = data["polymarket"]["market_title"]
    asset = instruments_map[title]["asset"]

    spot_symbol = "btc_usd" if asset == "BTC" else "eth_usd"
    spot = float(get_spot_price(spot_symbol))

    inst_k1 = instruments_map[title]["k1"]
    inst_k2 = instruments_map[title]["k2"]
    if not inst_k1 or not inst_k2:
        raise Exception(f"❌ 无法找到 {title} 对应的 Deribit 期权合约")

    # === Deribit 报价（BTC单位，不再除以spot）===
    deribit_list = get_deribit_option_data(currency=asset)
    k1_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k1), {})
    k2_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k2), {})

    if not k1_info or not k2_info:
        raise Exception("missing deribit option quotes")

    k1_bid_btc = float(k1_info["bid_price"])
    k1_ask_btc = float(k1_info["ask_price"])
    k2_bid_btc = float(k2_info["bid_price"])
    k2_ask_btc = float(k2_info["ask_price"])
    k1_mid_btc = (k1_bid_btc + k1_ask_btc) / 2.0
    k2_mid_btc = (k2_bid_btc + k2_ask_btc) / 2.0

    # === 转换为USD供test算法使用 ===
    k1_bid_usd = k1_bid_btc * spot
    k1_ask_usd = k1_ask_btc * spot
    k2_bid_usd = k2_bid_btc * spot
    k2_ask_usd = k2_ask_btc * spot
    k1_mid_usd = k1_mid_btc * spot
    k2_mid_usd = k2_mid_btc * spot

    k1_iv = float(k1_info["mark_iv"])
    k2_iv = float(k2_info["mark_iv"])
    k1_fee_approx = float(k1_info["fee"])
    k2_fee_approx = float(k2_info["fee"])

    # PRD 4.1：使用低执行价 K1 的 IV 做 σ
    if k1_iv > 0:
        mark_iv = k1_iv
    elif k2_iv > 0:
        # 兜底：K1 的 IV 异常时，用 K2
        mark_iv = k2_iv
    else:
        raise Exception("iv pool wrong")

    event_id = PolymarketAPI.get_event_id_public_search(data["polymarket"]["event_title"])
    market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
    market_data = PolymarketAPI.get_market_by_id(market_id)
    outcome_prices = market_data.get("outcomePrices")
    yes_price, no_price = 0.0, 0.0
    if outcome_prices:
        prices = eval(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
        yes_price, no_price = float(prices[0]), float(prices[1])

    tokens = PolymarketAPI.get_clob_token_ids_by_market(market_id)
    yes_token_id = tokens["yes_token_id"]
    no_token_id = tokens["no_token_id"]

    k1_strike = float(data["deribit"]["k1_strike"])
    k2_strike = float(data["deribit"]["k2_strike"])
    K_poly = (k1_strike + k2_strike) / 2.0

    now_ms = time.time() * 1000
    if instruments_map[title]["k1_expiration_timestamp"] != instruments_map[title]["k2_expiration_timestamp"]:
        raise Exception("k1_expiration_timestamp not equal")

    T = (instruments_map[title]["k1_expiration_timestamp"] - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
    T = max(T, 0.0)
    r = 0.05

    deribit_prob = bs_probability_gt(
        S=spot, K=K_poly, T=T, sigma=mark_iv / 100.0, r=r
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    table = Table(title=f"🎯 {title} | {timestamp}", box=box.MINIMAL_DOUBLE_HEAD, border_style="cyan")
    table.add_column("指标", justify="left", style="bold")
    table.add_column("数值", justify="right")
    table.add_row("Asset", asset)
    table.add_row("Spot", f"{spot:.2f}")
    table.add_row("YES / NO", f"{yes_price:.4f} / {no_price:.4f}")
    table.add_row("K1/K2 Mid (BTC)", f"{k1_mid_btc:.6f} / {k2_mid_btc:.6f}")
    table.add_row("K1/K2 Mid (USD)", f"{k1_mid_usd:.2f} / {k2_mid_usd:.2f}")
    table.add_row("IV (K1/K2)", f"{k1_iv:.3f} / {k2_iv:.3f}")
    table.add_row("Vol Used", f"{mark_iv:.3f}")
    table.add_row("Deribit Prob", f"{deribit_prob:.4f}")
    console.print(table)

    for inv in investments:
        inv_base_usd = float(inv)
        inv_base_btc = inv_base_usd / spot

        try:
            pm_yes_open = await get_polymarket_slippage(yes_token_id, inv_base_usd, side="buy", amount_type="usd")
            pm_yes_avg_open = float(pm_yes_open["avg_price"])
            pm_yes_shares_open = float(pm_yes_open["shares_executed"])
            pm_yes_slip_open = float(pm_yes_open["slippage_pct"]) / 100.0
            pm_yes_close = await get_polymarket_slippage(yes_token_id, pm_yes_shares_open, side="sell", amount_type="shares")
            pm_yes_avg_close = float(pm_yes_close["avg_price"])
            pm_yes_slip_close = float(pm_yes_close["slippage_pct"]) / 100.0
            pm_no_open = await get_polymarket_slippage(no_token_id, inv_base_usd, side="buy", amount_type="usd")
            pm_no_avg_open = float(pm_no_open["avg_price"])
            pm_no_slip_open = float(pm_no_open["slippage_pct"]) / 100.0
            pm_no_close = await get_polymarket_slippage(no_token_id, pm_no_open["shares_executed"], side="sell", amount_type="shares")
            pm_no_avg_close = float(pm_no_close["avg_price"])
            pm_no_slip_close = float(pm_no_close["slippage_pct"]) / 100.0
        except Exception as e:
            raise Exception("Polymarket slippage wrong") from e

        pos_in = PositionInputs(
            inv_base_usd=inv_base_usd,
            call_k1_bid_btc=k1_bid_btc,
            call_k2_ask_btc=k2_ask_btc,
            call_k1_ask_btc=k1_ask_btc,
            call_k2_bid_btc=k2_bid_btc,
            btc_usd=spot,
        )

        contracts_s1, s1_income_usd = strategy1_position_contracts(pos_in)
        contracts_s2, s2_cost_usd = strategy2_position_contracts(pos_in, poly_no_entry=no_price)
        amount_contracts = max(abs(contracts_s1), abs(contracts_s2))

        im_value_btc = float(await get_testnet_initial_margin(
            deribitUserCfg,
            amount=amount_contracts,
            instrument_name=inst_k1,
        ))
        im_value_usd = im_value_btc * spot  # ✅ 只乘一次

        calc_input = CalculationInput(
            S=spot,
            K=k1_strike,
            T=T,
            r=r,
            sigma=mark_iv / 100.0,
            K1=k1_strike,
            K_poly=K_poly,
            K2=k2_strike,
            Inv_Base=inv_base_usd,
            Call_K1_Bid=k1_bid_usd,
            Call_K2_Ask=k2_ask_usd,
            Price_No_entry=no_price,
            Call_K1_Ask=k1_ask_usd,
            Call_K2_Bid=k2_bid_usd,
            Price_Option1=k1_mid_usd,
            Price_Option2=k2_mid_usd,
            BTC_Price=spot,
            Slippage_Rate=max(pm_yes_slip_open, pm_no_slip_open),
            Margin_Requirement=im_value_usd,
            Total_Investment=inv_base_usd,
            pme_params=PMEParams(),
            contracts=float(amount_contracts),
            days_to_expiry=float(T * 365.0),
        )

        result = main_calculation(
            calc_input,
            use_pme_margin=True,
            calculate_annualized=True,
            pm_yes_price=yes_price,
            calculate_greeks=False,
            bs_edge_threshold=0.03
        )

        ev_yes = float(result.expected_pnl_strategy1.Total_Expected)
        ev_no = float(result.expected_pnl_strategy2.Total_Expected)
        total_costs_yes = float(result.costs.Total_Cost)
        total_costs_no = float(result.costs.Total_Cost)

        im_final_usd = im_value_usd

        console.print(
            f"💰 {inv_base_usd:.0f} | EV_yes={ev_yes:.2f} | EV_no={ev_no:.2f} | IM={im_final_usd:.2f} | "
            f"EV/IM_yes={(ev_yes/im_final_usd):.3f} | EV/IM_no={(ev_no/im_final_usd):.3f}"
        )

        save_result_csv({
            # === 基础信息 ===
            "timestamp": timestamp,
            "market_title": title,
            "asset": asset,
            "investment": inv_base_usd,

            # === 市场价格相关 ===
            "spot": spot,
            "poly_yes_price": yes_price,
            "poly_no_price": no_price,
            "deribit_prob": deribit_prob,

            # === 合约名 ===
            "k1_instrument": inst_k1,
            "k2_instrument": inst_k2,

            # === Deribit 参数 ===
            "K1": k1_strike,
            "K2": k2_strike,
            "K_poly": K_poly,
            "T": T,
            "days_to_expiry": calc_input.days_to_expiry,
            "sigma": mark_iv / 100.0,
            "r": r,
            "k1_bid_btc": k1_bid_btc,
            "k1_ask_btc": k1_ask_btc,
            "k2_bid_btc": k2_bid_btc,
            "k2_ask_btc": k2_ask_btc,
            "k1_mid_usd": k1_mid_usd,
            "k2_mid_usd": k2_mid_usd,

            # === Polymarket & Slippage ===
            "pm_yes_slippage": pm_yes_slip_open,
            "pm_no_slippage": pm_no_slip_open,
            "slippage_rate_used": calc_input.Slippage_Rate,

            # === 成本 / 保证金 ===
            "total_costs_yes": total_costs_yes,
            "total_costs_no": total_costs_no,
            "IM_usd": im_final_usd,
            "IM_btc": im_value_btc,
            "contracts": amount_contracts,

            # === 策略计算相关参数 ===
            "Price_No_entry": calc_input.Price_No_entry,
            "Call_K1_Bid": calc_input.Call_K1_Bid,
            "Call_K1_Ask": calc_input.Call_K1_Ask,
            "Call_K2_Bid": calc_input.Call_K2_Bid,
            "Call_K2_Ask": calc_input.Call_K2_Ask,

            # === 最后两列必须是 EV ===
            "ev_yes": ev_yes,
            "ev_no": ev_no,
        }, output_csv)


async def main(config_path="config.yaml"):
    config = load_manual_data(config_path)
    deribitUserCfg = DeribitUserCfg(
        user_id=os.getenv("test_deribit_user_id", ""),
        client_id=os.getenv("test_deribit_client_id", ""),
        client_secret=os.getenv("test_deribit_client_secret", "")
    )

    investments = config["thresholds"]["INVESTMENTS"]
    output_csv = config["thresholds"]["OUTPUT_CSV"]
    day_offset = 3
    instruments_map = init_markets(config, day_offset=day_offset)

    console.print(Panel.fit("[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]", border_style="bright_cyan"))
    console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

    events = config["events"]

    while True:
        for data in events:
            try:
                await loop_event(
                    data,
                    deribitUserCfg,
                    investments,
                    output_csv,
                    instruments_map
                )
            except Exception as e:
                console.print(f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]")

        sleep_sec = config["thresholds"]["check_interval_sec"]
        console.print(f"\n[dim]⏳ 等待 {sleep_sec} 秒后重连 Deribit/Polymarket 数据流...[/dim]\n")
        time.sleep(sleep_sec)


if __name__ == "__main__":
    asyncio.run(main())
