import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..fetch_data.deribit.deribit_client import DeribitClient

logger = logging.getLogger(__name__)


def parse_timestamp(exp: Any) -> Optional[float]:
    """将配置中的到期时间字段统一转换为毫秒级时间戳。"""
    if isinstance(exp, (int, float)):
        return float(exp)
    if isinstance(exp, str):
        dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S UTC")
        return dt.replace(tzinfo=timezone.utc).timestamp() * 1000.0
    return None

def init_markets(
    events: list[dict], day_offset: int = 0, target_date: date | None = None
) -> Tuple[Dict[str, Dict[str, Any]], list[str]]:
    """
    根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC / ETH。

    优先使用显式给出的到期时间(k1_expiration / k2_expiration), 否则根据 day_offset 自动匹配。
    若实际合约到期日与 target_date 不符，则跳过该市场。
    """
    instruments_map: Dict[str, Dict[str, Any]] = {}
    skipped_titles: list[str] = []

    for m in events:
        title = m["polymarket"]["market_title"]
        asset = m["deribit"]["asset"]
        k1 = m["deribit"].get("k1_strike")
        k2 = m["deribit"].get("k2_strike")

        k1_explicit = parse_timestamp(m["deribit"].get("k1_expiration"))
        k2_explicit = parse_timestamp(m["deribit"].get("k2_expiration"))

        expected_expiration_date = target_date

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
            expected_expiration_date = datetime.fromtimestamp(
                k1_explicit / 1000.0, tz=timezone.utc
            ).date()
        else:
            # 先找到 K1 的合约
            inst_k1, k1_exp = DeribitClient.find_option_instrument(
                k1,
                call=True,
                currency=asset,
                day_offset=day_offset,
            )
            # 强制 K2 使用与 K1 相同的到期时间，确保一致性
            inst_k2, k2_exp = DeribitClient.find_option_instrument(
                k2,
                call=True,
                currency=asset,
                exp_timestamp=k1_exp,  # 使用 K1 的到期时间
            )

        if k1_exp != k2_exp:
            logger.warning(
                f"跳过市场 '{title}': K1 和 K2 到期时间不一致 "
                f"(K1: {datetime.fromtimestamp(k1_exp/1000, tz=timezone.utc)}, "
                f"K2: {datetime.fromtimestamp(k2_exp/1000, tz=timezone.utc)})"
            )
            skipped_titles.append(title)
            continue

        if expected_expiration_date:
            actual_expiration_date = datetime.fromtimestamp(
                k1_exp / 1000.0, tz=timezone.utc
            ).date()
            if actual_expiration_date != expected_expiration_date:
                logger.warning(
                    f"跳过市场 '{title}': 实际到期日 {actual_expiration_date} "
                    f"与预期 {expected_expiration_date} 不匹配"
                )
                skipped_titles.append(title)
                continue

        instruments_map[title] = {
            "k1_strike": k1,
            "k1": inst_k1,
            "k1_expiration_timestamp": k1_exp,
            "k2_strike": k2,
            "k2": inst_k2,
            "k2_expiration_timestamp": k2_exp,
            "asset": asset,
        }

    return instruments_map, skipped_titles