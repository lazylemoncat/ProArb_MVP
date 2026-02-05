import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, Optional

from py_clob_client.clob_types import MarketOrderArgs
from py_clob_client.order_builder.constants import SELL

from ..fetch_data.polymarket.polymarket_ws import PolymarketWS
from .fak_retry import FAKOrderAttempt, FAKRetryResult
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
        if len(trades) == 0:
            raise Exception("no trades")
        trade_size = trades[0]["size"]
        token_id = trades[0]["asset_id"]
        sell_order = client.create_market_order(
            MarketOrderArgs(
                token_id=token_id,
                amount=float(trade_size),
                side=SELL,
            )
        )
        client.post_order(sell_order)
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

    @staticmethod
    async def place_buy_with_retry(
        token_id: str,
        investment_usd: float,
        initial_limit_price: float,
        *,
        wait_seconds: float = 3.0,
        max_retries: int = 5,
        price_tolerance_pct: float = 2.0,
        min_remaining_usd: float = 1.0,
        max_total_seconds: float = 60.0,
    ) -> FAKRetryResult:
        """
        FAK 重试下单：下单后等待检查成交情况，未完成则用当前最优价格重试，
        直到完全成交或达到重试上限。

        参数:
            token_id: Polymarket token ID
            investment_usd: 目标投资金额 (USD)
            initial_limit_price: 首次下单限价
            wait_seconds: 每次下单后等待成交的时间（秒）
            max_retries: 最大重试次数
            price_tolerance_pct: 价格容忍度百分比，超过 initial_price * (1 + pct/100) 则停止
            min_remaining_usd: 剩余金额低于此值视为完成
            max_total_seconds: 总超时时间（秒）

        返回:
            FAKRetryResult 包含完整的重试过程记录
        """
        if investment_usd <= 0:
            raise ValueError("investment_usd must be > 0")
        if initial_limit_price <= 0 or initial_limit_price >= 1:
            raise ValueError("initial_limit_price must be in (0,1)")

        start_time = time.monotonic()
        total_filled_size = 0.0
        total_filled_cost = 0.0
        attempts: list[FAKOrderAttempt] = []
        order_ids: list[str] = []
        error_message: Optional[str] = None

        client = Polymarket_trade.get_client()
        remaining_usd = investment_usd
        current_price = initial_limit_price
        # 价格上限：超过此价格则停止重试
        max_price = initial_limit_price * (1 + price_tolerance_pct / 100)

        for attempt_num in range(1, max_retries + 1):
            # 检查剩余金额是否足够
            if remaining_usd < min_remaining_usd:
                break

            # 检查总超时
            elapsed = time.monotonic() - start_time
            if elapsed >= max_total_seconds:
                error_message = f"总超时 {max_total_seconds}s"
                break

            # 第二次及之后，获取当前最优 ask 价格
            if attempt_num > 1:
                try:
                    book = await PolymarketWS.fetch_orderbook(
                        asset_id=token_id, side="ask"
                    )
                    best_ask = book[0][0]
                    if best_ask > max_price:
                        error_message = (
                            f"当前最优 ask {best_ask} 超过价格容忍度 {max_price:.4f}"
                        )
                        break
                    current_price = round(best_ask, 2)
                except Exception as e:
                    error_message = f"获取盘口失败: {e}"
                    break

            # 计算本次下单份额
            size = int(remaining_usd / current_price)
            if size <= 0:
                error_message = (
                    f"计算出的份额为 0 (remaining={remaining_usd:.2f}, "
                    f"price={current_price})"
                )
                break

            # FAK 下单
            order_id: Optional[str] = None
            try:
                resp = Polymarket_trade.create_order(
                    client,
                    price=current_price,
                    size=float(size),
                    side="BUY",
                    token_id=token_id,
                )
                order_id = Polymarket_trade.extract_order_id(resp)
            except Exception as e:
                error_message = f"第 {attempt_num} 次下单失败: {e}"
                attempts.append(FAKOrderAttempt(
                    attempt_number=attempt_num,
                    order_id=None,
                    requested_size=float(size),
                    filled_size=0.0,
                    filled_cost=0.0,
                    avg_fill_price=0.0,
                    limit_price=current_price,
                    timestamp=datetime.now(timezone.utc),
                    raw_response={},
                ))
                break

            # 等待成交
            await asyncio.sleep(wait_seconds)

            # 检查成交状态
            filled_size = 0.0
            filled_cost = 0.0
            if order_id:
                filled_size, filled_cost, status = Polymarket_trade.get_order_status(
                    client, order_id
                )
                order_ids.append(order_id)

            # 记录本次尝试
            avg_price = filled_cost / filled_size if filled_size > 0 else 0.0
            attempts.append(FAKOrderAttempt(
                attempt_number=attempt_num,
                order_id=order_id,
                requested_size=float(size),
                filled_size=filled_size,
                filled_cost=filled_cost,
                avg_fill_price=avg_price,
                limit_price=current_price,
                timestamp=datetime.now(timezone.utc),
                raw_response=resp if isinstance(resp, dict) else {},
            ))

            # 更新总量
            total_filled_size += filled_size
            total_filled_cost += filled_cost
            remaining_usd = investment_usd - total_filled_cost

            logger.info(
                f"FAK 尝试 #{attempt_num}: "
                f"filled={filled_size}/{size}, "
                f"cost={filled_cost:.2f}, "
                f"remaining={remaining_usd:.2f}, "
                f"price={current_price}"
            )

        elapsed_seconds = time.monotonic() - start_time
        success = remaining_usd < min_remaining_usd
        overall_avg_price = (
            total_filled_cost / total_filled_size if total_filled_size > 0 else 0.0
        )

        result = FAKRetryResult(
            success=success,
            token_id=token_id,
            target_investment_usd=investment_usd,
            total_filled_size=total_filled_size,
            total_filled_cost=total_filled_cost,
            avg_fill_price=overall_avg_price,
            remaining_usd=max(remaining_usd, 0.0),
            attempt_count=len(attempts),
            attempts=attempts,
            order_ids=order_ids,
            error_message=error_message,
            elapsed_seconds=round(elapsed_seconds, 2),
        )

        logger.info(
            f"FAK 重试完成: success={success}, "
            f"attempts={len(attempts)}, "
            f"filled={total_filled_size}, "
            f"cost={total_filled_cost:.2f}, "
            f"elapsed={elapsed_seconds:.1f}s"
        )

        return result