from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from rich import box
from rich.table import Table

from core.deribit_client import get_spot_price, get_deribit_option_data
from core.polymarket_client import PolymarketClient
from strategy.probability_engine import bs_probability_gt


@dataclass
class DeribitMarketContext:
    """描述 Deribit 端市场情况的上下文信息。"""

    asset: str
    spot: float

    inst_k1: str
    inst_k2: str
    k1_strike: float
    k2_strike: float
    K_poly: float

    k1_bid_btc: float
    k1_ask_btc: float
    k2_bid_btc: float
    k2_ask_btc: float
    k1_mid_btc: float
    k2_mid_btc: float

    k1_bid_usd: float
    k1_ask_usd: float
    k2_bid_usd: float
    k2_ask_usd: float
    k1_mid_usd: float
    k2_mid_usd: float

    k1_iv: float
    k2_iv: float
    k1_fee_approx: float
    k2_fee_approx: float

    mark_iv: float
    deribit_prob: float


@dataclass
class PolymarketState:
    """描述 Polymarket 市场快照。"""

    event_title: str
    market_title: str
    event_id: str
    market_id: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str


def _choose_mark_iv(k1_iv: float, k2_iv: float) -> float:
    """简单地取两端 IV 的平均值作为用于 BS 概率计算的 vol。"""
    return (k1_iv + k2_iv) / 2.0


def build_deribit_context(
    data: Dict[str, Any],
    instruments_map: Dict[str, Dict[str, Any]],
) -> DeribitMarketContext:
    """构建 Deribit 端的上下文（包括 K1/K2 合约、报价、IV、概率等）。"""
    asset = data["asset"]
    title = data["polymarket"]["market_title"]
    K_poly = float(data["deribit"]["K_poly"])

    # === Spot ===
    spot = float(get_spot_price(asset))

    # === K1/K2 行权价 ===
    k1_strike = float(data["deribit"]["k1_strike"])
    k2_strike = float(data["deribit"]["k2_strike"])

    inst_k1 = instruments_map[title]["k1"]
    inst_k2 = instruments_map[title]["k2"]
    if not inst_k1 or not inst_k2:
        raise ValueError(f"无法找到 {title} 对应的 Deribit 期权合约")

    # === Deribit 报价（BTC 单位）===
    deribit_list = get_deribit_option_data(currency=asset)
    k1_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k1), {})
    k2_info = next((d for d in deribit_list if d.get("instrument_name") == inst_k2), {})
    if not k1_info or not k2_info:
        raise RuntimeError("missing deribit option quotes")

    k1_bid_btc = float(k1_info["bid_price"])
    k1_ask_btc = float(k1_info["ask_price"])
    k2_bid_btc = float(k2_info["bid_price"])
    k2_ask_btc = float(k2_info["ask_price"])
    k1_mid_btc = (k1_bid_btc + k1_ask_btc) / 2.0
    k2_mid_btc = (k2_bid_btc + k2_ask_btc) / 2.0

    # === 转为 USD，方便后续风控 / 收益计算 ===
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

    mark_iv = _choose_mark_iv(k1_iv, k2_iv)

    # === Black-Scholes 概率（Deribit 侧“认为”指数 > K_poly 的概率）===
    now_ts = time.time()
    k1_exp_ts = instruments_map[title]["k1_expiration_timestamp"] / 1000.0
    # 使用 K1 到期时间估计 T
    T = max(k1_exp_ts - now_ts, 1.0)  # 至少给一点时间，避免 0

    deribit_prob = bs_probability_gt(
        spot=spot,
        strike=K_poly,
        ttm=T / (365 * 24 * 3600),
        iv=mark_iv,
    )

    return DeribitMarketContext(
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
        deribit_prob=deribit_prob,
    )


def build_polymarket_state(data: Dict[str, Any]) -> PolymarketState:
    """构建 Polymarket 市场快照。"""
    event_title = data["polymarket"]["event_title"]
    market_title = data["polymarket"]["market_title"]

    event_id = PolymarketClient.get_event_id_public_search(event_title)
    market_id = PolymarketClient.get_market_id_by_market_title(event_id, market_title)
    market_data = PolymarketClient.get_market_by_id(market_id)
    tokens = PolymarketClient.get_clob_token_ids_by_market(market_id)

    outcome_prices = market_data.get("outcomePrices")
    yes_price, no_price = 0.0, 0.0
    if outcome_prices:
        if isinstance(outcome_prices, str):
            try:
                prices = ast.literal_eval(outcome_prices)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"Invalid outcomePrices format: {outcome_prices!r}") from exc
        else:
            prices = outcome_prices
        if len(prices) >= 2:
            yes_price, no_price = float(prices[0]), float(prices[1])
        else:
            raise ValueError(f"Unexpected outcomePrices length: {len(prices)}")

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
    """生成终端展示用的汇总表。"""
    table = Table(title="Deribit x Polymarket Arbitrage", box=box.SIMPLE_HEAVY)

    table.add_column("Field", style="bold")
    table.add_column("Value")

    if timestamp:
        table.add_row("Timestamp (UTC)", timestamp)

    table.add_row("Polymarket Event", poly_ctx.event_title)
    table.add_row("Polymarket Market", poly_ctx.market_title)

    table.add_row(
        "YES / NO",
        f"{poly_ctx.yes_price:.4f} / {poly_ctx.no_price:.4f}",
    )

    table.add_row("Asset", deribit_ctx.asset)
    table.add_row("Spot", f"{deribit_ctx.spot:.2f}")
    table.add_row(
        "K1 / K2 Strike",
        f"{deribit_ctx.k1_strike:.2f} / {deribit_ctx.k2_strike:.2f}",
    )
    table.add_row("Polymarket K", f"{deribit_ctx.K_poly:.2f}")

    table.add_row(
        "K1 Bid/Ask (USD)",
        f"{deribit_ctx.k1_bid_usd:.2f} / {deribit_ctx.k1_ask_usd:.2f}",
    )
    table.add_row(
        "K2 Bid/Ask (USD)",
        f"{deribit_ctx.k2_bid_usd:.2f} / {deribit_ctx.k2_ask_usd:.2f}",
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
