from core.DeribitStream import DeribitStream


def init_markets(config):
    """根据行权价为每个事件找出 Deribit 的 K1/K2 合约名，并记录资产类型 BTC/ETH。"""
    instruments_map = {}
    for m in config["events"]:
        title = m["polymarket"]["market_title"]
        asset = m.get("asset", "BTC").upper()
        k1 = m["deribit"]["k1_strike"]
        k2 = m["deribit"]["k2_strike"]
        # inst_k1, k1_expiration_timestamp = DeribitStream.find_month_future_by_strike(k1, call=True, currency=asset)
        # inst_k2, k2_expiration_timestamp = DeribitStream.find_month_future_by_strike(k2, call=True, currency=asset)
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