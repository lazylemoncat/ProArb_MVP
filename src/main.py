import asyncio
import os
import time
from datetime import datetime, timezone
import traceback
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.deribit_api import calc_slippage, get_orderbook, get_spot_price, get_testnet_initial_margin
from core.DeribitStream import DeribitStream
from core.get_deribit_option_data import get_deribit_option_data
from core.get_polymarket_slippage import get_polymarket_slippage
from core.PolymarketAPI import PolymarketAPI
from strategy.expected_value import (
    EVInputs,
    compute_both_strategies
)
from strategy.models import CostParams, StrategyContext

from strategy.probability_engine import bs_probability_gt
from utils.dataloader import load_manual_data
from utils.save_result import save_result_csv

console = Console()
load_dotenv()

def require_float(data: dict, key: str, k_dir: str) -> float:
    """
    从 dict 中强制获取 key 对应的浮点数：
    - 如果 key 不存在 → KeyError
    - 如果 value 是 None 或无法转为 float → ValueError
    """
    value = data.get(key)
    if value is None:
        raise KeyError(f"{k_dir}Key '{key}' is missing or is None in {data}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Value of '{key}' is not a valid float: {value!r}")

def init_markets(config):
    """根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC/ETH。"""
    instruments_map = {}
    for m in config["events"]:
        title = m["polymarket"]["market_title"]
        asset = m.get("asset", "BTC").upper()
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]
        inst_k1, k1_expiration_timestamp = DeribitStream.find_month_future_by_strike(k1, call=True, currency=asset)
        inst_k2, k2_expiration_timestamp = DeribitStream.find_month_future_by_strike(k2, call=True, currency=asset)
        instruments_map[title] = {
            "k1": inst_k1, 
            "k1_expiration_timestamp": k1_expiration_timestamp,
            "k2": inst_k2, 
            "k2_expiration_timestamp": k2_expiration_timestamp,
            "asset": asset
        }
    return instruments_map

async def loop_event(
        data,
        deribit_user_id,
        client_id,
        client_secret,
        investments,
        output_csv,
        instruments_map
    ):
    title = data["polymarket"]["market_title"]
    asset = instruments_map[title]["asset"]

    # === Spot 获取（BTC 或 ETH）===
    spot_symbol = "btc_usd" if asset == "BTC" else "eth_usd"
    spot = float(get_spot_price(spot_symbol))

    # === Deribit 合约名 ===
    inst_k1 = instruments_map[title]["k1"]
    inst_k2 = instruments_map[title]["k2"]
    if not inst_k1 or not inst_k2:
        raise Exception("❌ 无法找到 {title} 对应的 Deribit 期权合约")

    # === 批量获取期权数据（含 bid/ask/iv/fee）===
    deribit_list = get_deribit_option_data(currency=asset)
    k1_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k1), {})
    k2_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k2), {})

    k1_bid = require_float(k1_info, "bid_price", "k1")
    k1_ask = require_float(k1_info, "ask_price", "k1")
    k2_bid = require_float(k2_info, "bid_price", "k2")
    k2_ask = require_float(k2_info, "ask_price", "k2")
    k1_mid = (k1_bid + k1_ask) / 2
    k2_mid = (k2_bid + k2_ask) / 2
    k1_iv = require_float(k1_info, "mark_iv", "k1")
    k2_iv = require_float(k2_info, "mark_iv", "k2")
    k1_fee = require_float(k1_info, "fee", "k1")
    k2_fee = require_float(k2_info, "fee", "k2")


    # === 波动率：用 K1/K2 的有效 IV 均值兜底 ===
    iv_pool = [v for v in (k1_iv, k2_iv) if v > 0]
    if len(iv_pool) > 0:
        mark_iv = sum(iv_pool) / len(iv_pool)
    else:
        raise Exception("iv pool wrong")

    # === Polymarket YES/NO 实时价格 ===
    event_id = PolymarketAPI.get_event_id_public_search(data["polymarket"]["event_title"])
    market_id = PolymarketAPI.get_market_id_by_market_title(event_id, title)
    market_data = PolymarketAPI.get_market_by_id(market_id)
    outcome_prices = market_data.get("outcomePrices")
    yes_price, no_price = None, None
    if outcome_prices:
        try:
            prices = eval(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            yes_price, no_price = float(prices[0]), float(prices[1])
        except Exception:
            raise Exception("prices wrong")

    tokens = PolymarketAPI.get_clob_token_ids_by_market(market_id)
    yes_token_id = tokens.get("yes_token_id", "")
    no_token_id = tokens.get("no_token_id", "")

    # === 其它模型参数 ===
    k1_strike = float(data["deribit"]["k1_strike"])
    k2_strike = float(data["deribit"]["k2_strike"])
    K_poly = (k1_strike + k2_strike) / 2.0
    # T = 8.0 / 365.0
    now_ms = time.time() * 1000
    if instruments_map[title]["k1_expiration_timestamp"] != instruments_map[title]["k2_expiration_timestamp"]: 
        raise Exception("k1_expiration_timestamp not equal")

    T = (instruments_map[title]["k1_expiration_timestamp"] - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
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
        slip_yes = None
        slippage_yes = None
        slip_no = None
        slippage_no = None
        try:
            slip_yes = await get_polymarket_slippage(yes_token_id, inv, side="buy")
            slip_yes_open = await get_polymarket_slippage(yes_token_id, inv, side="buy", amount_type="usd")
            shares_yes = slip_yes_open["shares_executed"]
            slippage_yes = float(slip_yes.get("slippage_pct")) / 100.0
            slip_yes_close = await get_polymarket_slippage(yes_token_id, shares_yes, side="sell", amount_type="shares")
            slippage_yes_close = slip_yes_close.get("slippage_pct") / 100.0
        except Exception as e:
            raise Exception("slippage_yes wrong", e)
        try:
            slip_no = await get_polymarket_slippage(no_token_id, inv, side="buy")
            slip_no_close = await get_polymarket_slippage(no_token_id, inv, side="sell", amount_type="usd")
            slippage_no = float(slip_no.get("slippage_pct")) / 100.0
            shares_no = slip_no_close["shares_executed"]
            slip_no_close = await get_polymarket_slippage(no_token_id, shares_no, side="sell", amount_type="shares")
            slippage_no_close = slip_no_close.get("slippage_pct") / 100.0
        except Exception as e:
            raise Exception("slippage_no wrong", slip_no, slippage_no, e)

        # 测试网初始保证金（IM）
        # Deribit 垂直价差（熊市）净收入 = 卖K1 - 买K2（单位 BTC）
        actual_inv_yes = slip_yes.get("total_cost_usd", inv)   # YES 买入实际花费
        actual_inv_no  = slip_no.get("total_cost_usd", inv)    # NO  买入实际花费

        # 第二步：选择最小的成交额，避免一边成交一边没成交对冲失衡
        actual_inv = min(actual_inv_yes, actual_inv_no)

        # 第三步：计算缩放比例（部分成交）
        scale = actual_inv / inv
        net_credit_btc = (k1_bid / spot) - (k2_ask / spot)
        net_credit_usd = net_credit_btc * spot  # 换算为 USD

        # 第四步：同步缩放 Deribit 垂直价差的合约数量
        if net_credit_usd > 0:
            amount_contracts = (inv / net_credit_usd) * scale
        else:
            amount_contracts = 0

        # 第五步：更新 inv，后续 EV 和成本都基于实际投资
        inv = actual_inv

        # net_credit_btc = (k1_bid / spot) - (k2_ask / spot)
        # net_credit_usd = net_credit_btc * spot  # 换算为 USD
        # # 如果净收入小于等于0，说明没有套利空间，为避免除0，这里合约数设为0
        # if net_credit_usd > 0:
        #     amount_contracts = inv / net_credit_usd
        # else:
        #     amount_contracts = 0

        # amount_contracts = inv / (k1_mid * spot)
        im_value_btc = float(await get_testnet_initial_margin(
                            user_id=deribit_user_id,
                            client_id=client_id,
                            client_secret=client_secret,
                            amount=amount_contracts,
                            instrument_name=inst_k1,
                        )
        )
        im_value_usd = im_value_btc * spot

        # === 计算 Deribit 滑点（买K1，看涨期权方向为buy，做空则为sell）===
        try:
            order_book_k1 = await get_orderbook(inst_k1, depth=2000)
            print(order_book_k1)
            # 买入K1（对应策略1开仓）
            slip_deri_buy, avg_price_buy, best_price_buy, status = calc_slippage(order_book_k1, amount_contracts, side="buy")
            # 卖出K1（对应平仓或策略2）
            slip_deri_sell, avg_price_sell, best_price_sell, status = calc_slippage(order_book_k1, amount_contracts, side="sell")
            if slip_deri_buy is None or slip_deri_sell is None:
                raise Exception("no_liquidity")
        except Exception as e:
            raise Exception("Deribit slippage wrong", e)


        k1_bid_btc = k1_bid / spot
        k1_ask_btc = k1_ask / spot
        k2_bid_btc = k2_bid / spot
        k2_ask_btc = k2_ask / spot
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
            call_k1_bid_btc=k1_bid_btc,
            call_k2_ask_btc=k2_ask_btc,
            call_k1_ask_btc=k1_ask_btc,
            call_k2_bid_btc=k2_bid_btc,
            btc_usd=spot,                # 对 BTC/ETH 都表示“合约计价币的 USD 价格”
            inv_base_usd=float(inv),
            margin_requirement_usd=im_value_usd,
            slippage_open_s1=slippage_yes + slip_deri_sell,       # 策略1开仓（YES + 卖Call）
            slippage_close_s1=slippage_yes_close + slip_deri_buy,  # 策略1平仓（卖YES + 买Call）
            slippage_open_s2=slippage_no + slip_deri_buy,         # 策略2开仓（NO + 买Call）
            slippage_close_s2=slippage_no_close + slip_deri_sell   # 策略2平仓（卖NO + 卖Call）
        )

        # === 构造 CostParams（只用真实存在的字段）===
        cost_params = CostParams(
            margin_requirement_usd=im_value_usd,
            risk_free_rate=r,
            # 其它字段使用默认值：deribit_fee_cap_btc/deribit_fee_rate/gas_open_usd/gas_close_usd
        )
        # === 策略 1：做多 YES + 做空 Deribit 垂直价差 ===
        # === 策略 2：做多 NO(=做空 YES) + 做多 Deribit 垂直价差 ===
        strategyContext = StrategyContext(ev_inputs=ev_in, cost_params=cost_params, poly_no_entry=no_price)

        result = compute_both_strategies(strategyContext)
        ev_yes, ev_no = float(result["strategy1"]["total_ev"]), float(result["strategy2"]["total_ev"])
        total_costs_yes = float(result["strategy1"].get("total_cost"))
        total_costs_no = float(result["strategy2"].get("total_cost"))

        # === 保存结果 ===
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
                "slippage_open_s1": slippage_yes + slip_deri_sell,
                "slippage_close_s1": slippage_yes_close + slip_deri_buy,
                "slippage_open_s2": slippage_no + slip_deri_buy,
                "slippage_close_s2": slippage_no_close + slip_deri_sell,
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


async def main(config_path="config.yaml"):
    config = load_manual_data(config_path)
    deribit_user_id = os.getenv("test_deribit_user_id", "")
    client_id = os.getenv("test_deribit_client_id", "")
    client_secret = os.getenv("test_deribit_client_secret", "")

    investments = config["thresholds"]["INVESTMENTS"]
    output_csv = config["thresholds"]["OUTPUT_CSV"]
    instruments_map = init_markets(config)

    console.print(Panel.fit("[bold cyan]Deribit x Polymarket Arbitrage Monitor[/bold cyan]", border_style="bright_cyan"))
    console.print("\n🚀 [bold yellow]开始实时套利监控...[/bold yellow]\n")

    events = config["events"]

    while True:
        for data in events:
            try:
                await loop_event(
                    data,
                    deribit_user_id,
                    client_id,
                    client_secret,
                    investments,
                    output_csv,
                    instruments_map
                )
            except Exception as e:
                console.print(f"❌ [red]处理 {data['polymarket']['market_title']} 时出错: {e}[/red]")
                traceback.print_exc()   # 打印完整的错误堆栈

        sleep_sec = config["thresholds"]["check_interval_sec"]
        console.print(f"\n[dim]⏳ 等待 {sleep_sec} 秒后重连 Deribit/Polymarket 数据流...[/dim]\n")
        time.sleep(sleep_sec)


if __name__ == "__main__":
    asyncio.run(main())
