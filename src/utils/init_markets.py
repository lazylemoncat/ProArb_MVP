from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..fetch_data.deribit_client import DeribitClient


def parse_timestamp(exp: Any) -> Optional[float]:
    """将配置中的到期时间字段统一转换为毫秒级时间戳。"""
    if isinstance(exp, (int, float)):
        return float(exp)
    if isinstance(exp, str):
        dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S UTC")
        return dt.replace(tzinfo=timezone.utc).timestamp() * 1000.0
    return None


def init_markets(config: Dict[str, Any], day_offset: int = 0) -> Dict[str, Dict[str, Any]]:
    """
    根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC / ETH。

    优先使用显式给出的到期时间（k1_expiration / k2_expiration），否则根据 day_offset 自动匹配。
    """
    instruments_map: Dict[str, Dict[str, Any]] = {}

    for m in config["events"]:
        title = m["polymarket"]["market_title"]
        asset = m["deribit"]["asset"]
        k1 = m["deribit"].get("k1_strike")
        k2 = m["deribit"].get("k2_strike")

        k1_explicit = parse_timestamp(m["deribit"].get("k1_expiration"))
        k2_explicit = parse_timestamp(m["deribit"].get("k2_expiration"))

        if k1_explicit and k2_explicit:
            inst_k1, k1_exp = DeribitClient.find_option_instrument(
                k1,
                call=True,
                currency=asset,
                exp_timestamp=k1_explicit,
            )
            inst_k2, k2_exp = DeribitClient.find_option_instrument(
                k2,
                call=True,
                currency=asset,
                exp_timestamp=k2_explicit,
            )
        else:
            inst_k1, k1_exp = DeribitClient.find_option_instrument(
                k1,
                call=True,
                currency=asset,
                day_offset=day_offset,
            )
            inst_k2, k2_exp = DeribitClient.find_option_instrument(
                k2,
                call=True,
                currency=asset,
                day_offset=day_offset,
            )

        instruments_map[title] = {
            "k1": inst_k1,
            "k1_expiration_timestamp": k1_exp,
            "k2": inst_k2,
            "k2_expiration_timestamp": k2_exp,
            "asset": asset,
        }

    return instruments_map
