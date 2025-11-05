import asyncio
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.deribit_api import get_spot_price, get_testnet_initial_margin
from core.DeribitStream import DeribitStream
from core.get_deribit_option_data import get_deribit_option_data
from core.get_polymarket_slippage import get_polymarket_slippage
from core.PolymarketAPI import PolymarketAPI
from strategy.expected_value import (
    EVInputs,
    expected_values_strategy1,
    expected_values_strategy2,
)
from strategy.models import CostParams

from strategy.probability_engine import bs_probability_gt
from utils.dataloader import load_manual_data
from utils.save_result import save_result_csv

console = Console()
load_dotenv()

EPS = 1e-8

def safe_price(bid, ask, mark):
    """
    返回处理后的 (bid, ask)
    - 如果 bid 或 ask <= 0，则尝试使用 mark
    - 若 mark 也为 0，则用极小值 EPS 兜底
    """
    if bid is None or bid <= 0:
        bid = mark if mark and mark > 0 else EPS
    if ask is None or ask <= 0:
        ask = mark if mark and mark > 0 else EPS
    return bid, ask


def init_markets(config):
    """根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC/ETH。"""
    instruments_map = {}
    for m in config["events"]:
        title = m["polymarket"]["market_title"]
        asset = m.get("asset", "BTC").upper()
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]
        inst_k1, k1_expiration_timestamp = DeribitStream.find_option_instrument(k1, call=True, currency=asset)
        inst_k2, k2_expiration_timestamp = DeribitStream.find_option_instrument(k2, call=True, currency=asset)
        instruments_map[title] = {
            "k1": inst_k1, 
            "k1_expiration_timestamp": k1_expiration_timestamp,
            "k2": inst_k2, 
            "k2_expiration_timestamp": k2_expiration_timestamp,
            "asset": asset
        }
    return instruments_map


async def main(config_path="config.yaml"):
    deribit_user_id = os.getenv("test_deribit_user_id", "")
    client_id = os.getenv("test_deribit_client_id", "")
    client_secret = os.getenv("test_deribit_client_secret", "")
    config = load_manual_data(config_path)
    events = config["events"]
    investments = config["thresholds"]["INVESTMENTS"]
    output_csv = config["thresholds"]["OUTPUT_CSV"]

    instruments_map = init_markets(config)

    console.print(Panel.fit("[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]", border_style="bright_cyan"))
    console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

    while True:
        for data in events:
            try:
                title = data["polymarket"]["market_title"]
                asset = instruments_map[title]["asset"]

                # === Spot 获取（BTC 或 ETH）===
                spot_symbol = "btc_usd" if asset == "BTC" else "eth_usd"
                spot = float(get_spot_price(spot_symbol) or 0.0)

                # === Deribit 合约名 ===
                inst_k1 = instruments_map[title]["k1"]
                inst_k2 = instruments_map[title]["k2"]
                if not inst_k1 or not inst_k2:
                    console.print(f"[red]❌ 无法找到 {title} 对应的 Deribit 期权合约[/red]")
                    continue

                # === 批量获取期权数据（含 bid/ask/iv/fee）===
                deribit_list = get_deribit_option_data(currency=asset)
                k1_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k1), {})
                k2_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k2), {})

                k1_bid = float(k1_info.get("bid_price") or 0.0)
                k1_ask = float(k1_info.get("ask_price") or 0.0)
                k2_bid = float(k2_info.get("bid_price") or 0.0)
                k2_ask = float(k2_info.get("ask_price") or 0.0)
                k1_mark = float(k1_info.get("mark_price") or 0.0)
                k2_mark = float(k2_info.get("mark_price") or 0.0)
                k1_bid, k1_ask = safe_price(k1_bid, k1_ask, k1_mark)
                k2_bid, k2_ask = safe_price(k2_bid, k2_ask, k2_mark)
                k1_mid = (k1_bid + k1_ask) / 2 if (k1_bid > 0 and k1_ask > 0) else 0.0
                k2_mid = (k2_bid + k2_ask) / 2 if (k2_bid > 0 and k2_ask > 0) else 0.0
                k1_iv = float(k1_info.get("mark_iv") or 0.0)
                k2_iv = float(k2_info.get("mark_iv") or 0.0)
                k1_fee = float(k1_info.get("fee") or 0.0)
                k2_fee = float(k2_info.get("fee") or 0.0)
                # deribit_fee_for_show = max(k1_fee, k2_fee)

                # === 波动率：用 K1/K2 的有效 IV 均值兜底 ===
                iv_pool = [v for v in (k1_iv, k2_iv) if v > 0]
                mark_iv = sum(iv_pool) / len(iv_pool) if iv_pool else 60.0

                # === Polymarket YES/NO 实时价格 ===
                event_id = PolymarketAPI.get_event_id_public_search(data["polymarket"]["event_title"])
                market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
                market_data = PolymarketAPI.get_market_by_id(market_id)
                outcome_prices = market_data.get("outcomePrices", None)
                yes_price, no_price = 0.0, 0.0
                if outcome_prices:
                    try:
                        prices = eval(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                        yes_price, no_price = float(prices[0]), float(prices[1])
                    except Exception:
                        pass

                tokens = PolymarketAPI.get_clob_token_ids_by_market(market_id)
                yes_token_id = tokens.get("yes_token_id", "")
                # no_token_id = tokens.get("no_token_id", "")

                # === 其它模型参数 ===
                k1_strike = float(data["deribit"]["k1_strike"])
                k2_strike = float(data["deribit"]["k2_strike"])
                K_poly = (k1_strike + k2_strike) / 2.0
                # T = 8.0 / 365.0
                now_ms = time.time() * 1000
                expiry_timestamp_ms = min(
                    instruments_map[title]["k1_expiration_timestamp"],
                    instruments_map[title]["k2_expiration_timestamp"]
                )
                T = (expiry_timestamp_ms - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
                T = max(T, 0)  # 防止负数
                r = 0.05

                deribit_prob = bs_probability_gt(
                    S=spot,
                    K=K_poly,
                    T=T,
                    sigma=mark_iv / 100.0,
                    r=r
                )

                # === 时间戳 ===
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # === 展示表格 ===
                table = Table(title=f"🎯 {title} | {timestamp}", box=box.MINIMAL_DOUBLE_HEAD, border_style="cyan")
                table.add_column("指标", justify="left", style="bold")
                table.add_column("数值", justify="right")
                table.add_row("Asset", asset)
                table.add_row("Spot", f"{spot:.2f}")
                table.add_row("YES Price", f"{yes_price:.4f}")
                table.add_row("NO Price", f"{no_price:.4f}")
                table.add_row("K1/K2 Mid", f"{k1_mid:.5f} / {k2_mid:.5f}")
                table.add_row("IV (K1/K2)", f"{k1_iv:.3f} / {k2_iv:.3f}")
                table.add_row("Vol Used", f"{mark_iv:.3f}")
                table.add_row("Fee (K1/K2)", f"{k1_fee:.6f} / {k2_fee:.6f}")
                table.add_row("Deribit Prob", f"{deribit_prob:.4f}")
                console.print(table)

                # === 多投资额策略计算 ===
                # inv 是 USD 单位
                for inv in investments:
                    # Polymarket 滑点（YES/NO 各取一次）
                    try:
                        slip_yes = await get_polymarket_slippage(yes_token_id, inv)
                        slippage_yes = float(slip_yes.get("slippage_pct", 0)) / 100.0
                    except Exception:
                        slippage_yes = 0.01
                    try:
                        # slip_no = get_polymarket_slippage_sync(no_token_id, inv)
                        # slippage_no = float(slip_no.get("slippage_pct", 0)) / 100.0
                        pass
                    except Exception:
                        # slippage_no = 0.01
                        pass

                    # 测试网初始保证金（IM）
                    amount_contracts = inv / (k1_mid * spot)
                    im_value_btc = float(await get_testnet_initial_margin(
                                        user_id=deribit_user_id,
                                        client_id=client_id,
                                        client_secret=client_secret,
                                        amount=amount_contracts,
                                        instrument_name=inst_k1,
                                    )
                    )
                    im_value_usd = im_value_btc * spot


                    # === 构造 EVInputs（字段名必须与 dataclass 完全一致）===
                    ev_in = EVInputs(
                        S=spot,
                        K1=k1_strike,
                        K_poly=K_poly,
                        K2=k2_strike,
                        T=T,
                        sigma=mark_iv / 100.0,
                        r=r,
                        poly_yes_price=yes_price,
                        call_k1_bid_btc=k1_bid,
                        call_k2_ask_btc=k2_ask,
                        call_k1_ask_btc=k1_ask,
                        call_k2_bid_btc=k2_bid,
                        btc_usd=spot,                # 对 BTC/ETH 都表示“合约计价币的 USD 价格”
                        inv_base_usd=float(inv),
                        margin_requirement_usd=im_value_usd,
                        slippage_rate_close=slippage_yes,  # 平仓滑点；另：策略2我们单独传 NO 价
                    )

                    # === 构造 CostParams（只用真实存在的字段）===
                    cost_params = CostParams(
                        margin_requirement_usd=im_value_usd,
                        risk_free_rate=r,
                        # 其它字段使用默认值：deribit_fee_cap_btc/deribit_fee_rate/gas_open_usd/gas_close_usd
                    )

                    # === 策略 1：做多 YES + 做空 Deribit 垂直价差 ===
                    ev_out_1 = expected_values_strategy1(ev_in, cost_params)
                    ev_yes = float(ev_out_1["total_ev"])
                    total_costs_yes = float(ev_out_1.get("total_cost", 0.0))

                    # === 策略 2：做多 NO(=做空 YES) + 做多 Deribit 垂直价差 ===
                    # ！！函数签名需要 poly_no_entry（NO 的入场价），以前调用缺这个参数会报错
                    ev_out_2 = expected_values_strategy2(ev_in, cost_params, poly_no_entry=no_price)
                    ev_no = float(ev_out_2["total_ev"])
                    total_costs_no = float(ev_out_2.get("total_cost", 0.0))

                    # === 保存结果（可按你的 ResultRecord 精简字段）===
                    save_result_csv(
                        {
                            "timestamp": timestamp,
                            "market_title": title,
                            "asset": asset,
                            "investment": inv,
                            "spot": spot,
                            "poly_yes_price": yes_price,
                            "poly_no_price": no_price,
                            "deribit_prob": deribit_prob,
                            "total_costs_yes": total_costs_yes,
                            "total_costs_no": total_costs_no,
                            "IM_usd": im_value_usd,
                            "IM_btc": im_value_btc,
                            "EV/IM_yes": (ev_yes / im_value_usd) if im_value_btc > 0 else None,
                            "EV/IM_no": (ev_no / im_value_usd) if im_value_btc > 0 else None,
                            "k1_bid": k1_bid,
                            "k1_ask": k1_ask,
                            "k2_bid": k2_bid,
                            "k2_ask": k2_ask,
                            "k1_strike": k1_strike,
                            "k2_strike": k2_strike,
                            "mark_iv": mark_iv,
                            "r": r,
                            "T": T,
                            "ev_yes": ev_yes,
                            "ev_no": ev_no,
                        },
                        output_csv,
                    )

                    # 控制台简报
                    if im_value_usd > 0:
                        console.print(
                            f"💰 {inv} | EV_yes={ev_yes:.2f} | EV_no={ev_no:.2f} | IM={im_value_usd:.2f} | "
                            f"EV/IM_yes={(ev_yes/im_value_usd):.3f}" + ("" if im_value_usd == 0 else f" | EV/IM_no={(ev_no/im_value_usd):.3f}")
                        )

                console.rule("[bold magenta]Next Market[/bold magenta]")

            except Exception as e:
                console.print(f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]")

        console.print("\n[dim]⏳ 等待 120 秒后重连 Deribit/Polymarket 数据流...[/dim]\n")
        time.sleep(120)


if __name__ == "__main__":
    asyncio.run(main())
