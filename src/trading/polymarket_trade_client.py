import logging
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, Optional

from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import SELL

from .polymarket_trade import Polymarket_trade

logger = logging.getLogger(__name__)

def _q_down(x: Decimal, decimals: int) -> Decimal:
    step = Decimal("1").scaleb(-decimals)  # 10**(-decimals)
    return x.quantize(step, rounding=ROUND_DOWN)

class Polymarket_trade_client:
    @staticmethod
    def early_exit(token_id: str, price: float):
        client = Polymarket_trade.get_client()
        trades = Polymarket_trade.get_trades(client, asset_id=token_id)
        trade_size = trades[0]["size"]
        token_id = trades[0]["asset_id"]
        sell_order = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=float(trade_size),
                side=SELL,
            )
        )
        return sell_order


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
        
        # 需要用 decimal 模块保证精度问题
        price = Decimal(str(limit_price))
        invest = _q_down(Decimal(str(investment_usd)), 2)          # maker: 2 decimals
        size = _q_down(invest / price, 4)                          # taker: 4 decimals
        cost = _q_down(size * price, 2)     

        if size <= 0 or cost <= 0:
            raise ValueError(f"Computed non-positive size/cost: size={size}, cost={cost}")
        
        logger.info(f"limit_price={price}, invest={invest}, size={size}, cost={cost}")

        client = Polymarket_trade.get_client()
        size = int(investment_usd / limit_price)
        resp = Polymarket_trade.create_order(
            client, 
            price=float(price), 
            size=float(size), 
            side="BUY", 
            token_id=token_id
        )
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