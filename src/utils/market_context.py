from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from rich import box
from rich.table import Table

from ..fetch_data.deribit_client import DeribitClient
from ..fetch_data.polymarket_client import PolymarketClient
from ..strategy.probability_engine import bs_probability_gt


@dataclass
class DeribitMarketContext:
    """聚合 Deribit 相关的行情与参数，方便后续计算和输出。"""
    title: str
    asset: str
    # 现货价格
    spot: float
    # 合约名称
    inst_k1: str
    inst_k2: str
    # k1 k2 代表的价格
    k1_strike: float
    k2_strike: float
    K_poly: float
    # BTC 计价
    k1_bid_btc: float
    k1_ask_btc: float
    k2_bid_btc: float
    k2_ask_btc: float
    k1_mid_btc: float
    k2_mid_btc: float
    # USD 计价
    k1_bid_usd: float
    k1_ask_usd: float
    k2_bid_usd: float
    k2_ask_usd: float
    k1_mid_usd: float
    k2_mid_usd: float
    # 波动率 / 手续费
    k1_iv: float
    k2_iv: float
    k1_fee_approx: float
    k2_fee_approx: float
    mark_iv: float
    # 时间与概率
    k1_expiration_timestamp: float
    T: float
    days_to_expairy: float
    r: float
    deribit_prob: float


@dataclass
class PolymarketState:
    """Polymarket 市场的快照。"""
    event_title: str
    market_title: str

    event_id: str
    market_id: str

    yes_price: float
    no_price: float

    yes_token_id: str
    no_token_id: str


def _choose_mark_iv(k1_iv: float, k2_iv: float) -> float:
    """根据 PRD 约定选择用于定价的 sigma."""
    if k1_iv > 0:
        return k1_iv
    if k2_iv > 0:
        return k2_iv
    raise ValueError("Both K1 / K2 IV are non-positive, cannot choose mark_iv")


def build_deribit_context(
    data: Dict[str, Any],
    instruments_map: Dict[str, Dict[str, Any]],
) -> DeribitMarketContext:
    """
    构建 Deribit 行情上下文，主要包含：
    - 现货价格
    - K1/K2 合约报价（BTC 和 USD）
    - 波动率、执行价、到期时间等参数
    """
    title = data["polymarket"]["market_title"]
    asset = instruments_map[title]["asset"]

    spot_symbol = "btc_usd" if asset.upper() == "BTC" else "eth_usd"
    spot = float(DeribitClient.get_spot_price(spot_symbol))

    inst_k1 = instruments_map[title]["k1"]
    inst_k2 = instruments_map[title]["k2"]
    if not inst_k1 or not inst_k2:
        raise ValueError(f"无法找到 {title} 对应的 Deribit 期权合约")

    # === Deribit 报价（BTC 单位）===
    deribit_list = DeribitClient.get_deribit_option_data(currency=asset)
    k1_info = next((d for d in deribit_list if d.instrument_name == inst_k1), None)
    k2_info = next((d for d in deribit_list if d.instrument_name == inst_k2), None)
    if k1_info is None or k2_info is None:
        raise RuntimeError("missing deribit option quotes")

    k1_bid_btc = float(k1_info.bid_price)
    k1_ask_btc = float(k1_info.ask_price)
    k2_bid_btc = float(k2_info.bid_price)
    k2_ask_btc = float(k2_info.ask_price)
    k1_mid_btc = (k1_bid_btc + k1_ask_btc) / 2.0
    k2_mid_btc = (k2_bid_btc + k2_ask_btc) / 2.0

    # === 转为 USD，方便后续风控 / 收益计算 ===
    k1_bid_usd = k1_bid_btc * spot
    k1_ask_usd = k1_ask_btc * spot
    k2_bid_usd = k2_bid_btc * spot
    k2_ask_usd = k2_ask_btc * spot
    k1_mid_usd = k1_mid_btc * spot
    k2_mid_usd = k2_mid_btc * spot

    k1_iv = float(k1_info.mark_iv)
    k2_iv = float(k2_info.mark_iv)
    k1_fee_approx = float(k1_info.fee)
    k2_fee_approx = float(k2_info.fee)

    mark_iv = _choose_mark_iv(k1_iv, k2_iv)

    k1_strike = float(data["deribit"]["k1_strike"])
    k2_strike = float(data["deribit"]["k2_strike"])
    # 优先使用配置里传入的 Polymarket 行权价，避免在不对称 offset 下偏离实际阈值
    K_poly_cfg = data.get("deribit", {}).get("K_poly")
    K_poly = float(K_poly_cfg) if K_poly_cfg is not None else (k1_strike + k2_strike) / 2.0

    now_ms = time.time() * 1000.0
    k1_exp_ts = float(instruments_map[title]["k1_expiration_timestamp"])
    k2_exp_ts = float(instruments_map[title]["k2_expiration_timestamp"])
    if k1_exp_ts != k2_exp_ts:
        raise ValueError("k1_expiration_timestamp not equal")

    # 天化到期时间 T
    T = (k1_exp_ts - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
    T = max(T, 0.0)
    r = 0.05

    deribit_prob = bs_probability_gt(
        S=spot, K=K_poly, T=T, sigma=mark_iv / 100.0, r=r
    )

    return DeribitMarketContext(
        title=title,
        asset=asset,
        spot=spot,
        inst_k1=inst_k1,
        inst_k2=inst_k2,
        k1_strike=k1_strike,
        k2_strike=k2_strike,
        K_poly=K_poly,
        k1_bid_btc=k1_bid_btc,
        k1_ask_btc=k1_ask_btc,
        k2_bid_btc=k2_bid_btc,
        k2_ask_btc=k2_ask_btc,
        k1_mid_btc=k1_mid_btc,
        k2_mid_btc=k2_mid_btc,
        k1_bid_usd=k1_bid_usd,
        k1_ask_usd=k1_ask_usd,
        k2_bid_usd=k2_bid_usd,
        k2_ask_usd=k2_ask_usd,
        k1_mid_usd=k1_mid_usd,
        k2_mid_usd=k2_mid_usd,
        k1_iv=k1_iv,
        k2_iv=k2_iv,
        k1_fee_approx=k1_fee_approx,
        k2_fee_approx=k2_fee_approx,
        mark_iv=mark_iv,
        k1_expiration_timestamp=k1_exp_ts,
        T=T,
        days_to_expairy=T * 365,
        r=r,
        deribit_prob=deribit_prob,
    )


def build_polymarket_state(data: Dict[str, Any]) -> PolymarketState:
    """构建 Polymarket 市场快照。"""
    event_title = data["polymarket"]["event_title"]
    market_title = data["polymarket"]["market_title"]

    event_id = PolymarketClient.get_event_id_public_search(event_title)
    market_id = PolymarketClient.get_market_id_by_market_title(event_id, market_title)
    market_data = PolymarketClient.get_market_data_by_market_title(event_id, market_title)

    outcome_prices = market_data.get("outcomePrices")
    yes_price, no_price = 0.0, 0.0
    if outcome_prices:
        if isinstance(outcome_prices, str):
            try:
                prices = ast.literal_eval(outcome_prices)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(
                    f"Invalid outcomePrices format: {outcome_prices!r}"
                ) from exc
        else:
            prices = outcome_prices
        if len(prices) >= 2:
            yes_price, no_price = float(prices[0]), float(prices[1])
        else:
            raise ValueError(f"Unexpected outcomePrices length: {len(prices)}")

    tokens = PolymarketClient.get_clob_token_ids_by_market_title(event_id, market_title)
    yes_token_id = tokens["yes_token_id"]
    no_token_id = tokens["no_token_id"]

    return PolymarketState(
        event_title=event_title,
        market_title=market_title,
        event_id=event_id,
        market_id=market_id,
        yes_price=yes_price,
        no_price=no_price,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
    )


def make_summary_table(
    deribit_ctx: DeribitMarketContext,
    poly_ctx: PolymarketState,
    timestamp: str | None = None,
) -> Table:
    """构造 rich.Table，用于主进程输出摘要信息。"""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    table = Table(
        title=f"{deribit_ctx.title} @ {timestamp}",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    table.add_column("字段", justify="left")
    table.add_column("数值", justify="right")

    table.add_row("Asset", deribit_ctx.asset)
    table.add_row("Spot", f"{deribit_ctx.spot:.2f}")
    table.add_row(
        "YES / NO",
        f"{poly_ctx.yes_price:.4f} / {poly_ctx.no_price:.4f}",
    )
    table.add_row(
        "K1/K2 Mid (BTC)",
        f"{deribit_ctx.k1_mid_btc:.6f} / {deribit_ctx.k2_mid_btc:.6f}",
    )
    table.add_row(
        "K1/K2 Mid (USD)",
        f"{deribit_ctx.k1_mid_usd:.2f} / {deribit_ctx.k2_mid_usd:.2f}",
    )
    table.add_row(
        "IV (K1/K2)",
        f"{deribit_ctx.k1_iv:.3f} / {deribit_ctx.k2_iv:.3f}",
    )
    table.add_row("Vol Used", f"{deribit_ctx.mark_iv:.3f}")
    table.add_row("Deribit Prob", f"{deribit_ctx.deribit_prob:.4f}")

    return table
