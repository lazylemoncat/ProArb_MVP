from core.DeribitStream import DeribitStream
from datetime import datetime, timezone

def parse_timestamp(exp):
    if isinstance(exp, (int, float)):
        return exp
    if isinstance(exp, str):
        dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S UTC")
        return dt.replace(tzinfo=timezone.utc).timestamp() * 1000
    return None

def init_markets(config, day_offset=0):
    """根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC/ETH。"""
    instruments_map = {}
    for m in config["events"]:
        title = m["polymarket"]["market_title"]
        asset = m.get("asset", "BTC").upper()
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]

        # ===== 新增：如果 config 里写了 instrument，优先使用 =====
        inst_k1 = m["deribit"].get("k1_instrument")
        inst_k2 = m["deribit"].get("k2_instrument")
        k1_exp = parse_timestamp(m["deribit"].get("k1_expiration"))
        k2_exp = parse_timestamp(m["deribit"].get("k2_expiration"))

        # 如果没有写，才自动搜索
        if not inst_k1 or not inst_k2:
            inst_k1, k1_exp = DeribitStream.find_option_instrument(
                k1, call=True, currency=asset, day_offset=day_offset
            )
            inst_k2, k2_exp = DeribitStream.find_option_instrument(
                k2, call=True, currency=asset, day_offset=day_offset
            )

        instruments_map[title] = {
            "k1": inst_k1,
            "k1_expiration_timestamp": k1_exp,
            "k2": inst_k2,
            "k2_expiration_timestamp": k2_exp,
            "asset": asset
        }
    return instruments_map