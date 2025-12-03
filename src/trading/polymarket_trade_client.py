from typing import Any, Dict, Optional
from .polymarket_trade import Polymarket_trade

class Polymarket_trade_client:
    @staticmethod
    def place_buy_by_investment(token_id: str, investment_usd: float, limit_price: float) -> tuple[Dict[str, Any], Optional[str]]:
        """
        按美元金额下 buy 单（size=investment/price）。
        返回 (raw_response, order_id)
        """
        if investment_usd <= 0:
            raise ValueError("investment_usd must be > 0")
        if limit_price <= 0 or limit_price >= 1:
            raise ValueError("limit_price must be in (0,1)")

        client = Polymarket_trade.get_client()
        size = float(investment_usd) / float(limit_price)
        resp = Polymarket_trade.create_order(client, price=float(limit_price), size=size, side="BUY", token_id=token_id)
        return resp, Polymarket_trade.extract_order_id(resp)

    @staticmethod
    def place_sell_by_size(token_id: str, size: float, limit_price: float) -> tuple[Dict[str, Any], Optional[str]]:
        """
        按给定 size 下 sell 单，用于回滚/平仓。

        返回 (raw_response, order_id)
        """
        if size <= 0:
            raise ValueError("size must be > 0")
        if limit_price <= 0 or limit_price >= 1:
            raise ValueError("limit_price must be in (0,1)")

        client = Polymarket_trade.get_client()
        resp = Polymarket_trade.create_order(client, price=float(limit_price), size=float(size), side="SELL", token_id=token_id)
        return resp, Polymarket_trade.extract_order_id(resp)