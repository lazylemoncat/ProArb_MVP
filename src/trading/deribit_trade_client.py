import logging
from typing import Any, Dict, List, Optional, Tuple

import websockets

from .deribit_trade import Deribit_trade, DeribitUserCfg

logger = logging.getLogger(__name__)

WS_URL = "wss://www.deribit.com/ws/api/v2"

class Deribit_trade_client:
    @staticmethod
    async def get_orderbook_prices(
        deribitUserCfg: DeribitUserCfg,
        instrument_name: str,
        depth: int = 3
    ):
        async with websockets.connect(WS_URL) as websocket:
            await Deribit_trade.websocket_auth(websocket, deribitUserCfg)
            orderbook = await Deribit_trade.get_orderbook_by_instrument_name(
                websocket,
                deribitUserCfg,
                instrument_name,
                depth=depth
            )
            res = orderbook.get("result", {})
            return {
                "bids": res.get("bids", []),
                "asks": res.get("asks", []),
            }

    @staticmethod
    async def buy(deribitUserCfg: DeribitUserCfg, amount: float, instrument_name: str) -> Dict[str, Any]:
        async with websockets.connect(WS_URL) as websocket:
            await Deribit_trade.websocket_auth(websocket, deribitUserCfg)
            return await Deribit_trade.open_position(
                websocket=websocket,
                amount=amount,
                deribitUserCfg=deribitUserCfg,
                instrument_name=instrument_name,
            )

    @staticmethod
    async def sell(deribitUserCfg: DeribitUserCfg, amount: float, instrument_name: str) -> Dict[str, Any]:
        async with websockets.connect(WS_URL) as websocket:
            await Deribit_trade.websocket_auth(websocket, deribitUserCfg)
            return await Deribit_trade.close_position(
                websocket=websocket,
                amount=amount,
                deribitUserCfg=deribitUserCfg,
                instrument_name=instrument_name,
            )

    @staticmethod
    async def execute_vertical_spread(
        deribitUserCfg: DeribitUserCfg,
        contracts: float,
        inst_k1: str,
        inst_k2: str,
        strategy: int,
    ) -> Tuple[List[Dict[str, Any]], List[Optional[str]], float]:
        """
        执行两腿牛市价差：
        - strategy=1: 卖牛差（short K1, long K2） => sell k1, buy k2
        - strategy=2: 买牛差（long K1, short K2） => buy k1, sell k2

        返回 (responses, order_ids, executed_amount)
        """
        amount = float(contracts)

        async with websockets.connect(WS_URL) as websocket:
            await Deribit_trade.websocket_auth(websocket, deribitUserCfg)

            resps: List[Dict[str, Any]] = []
            ids: List[Optional[str]] = []
            executed_amount = amount

            def _filled_amount(resp: Dict[str, Any], *, default: float) -> float:
                """
                Extract filled amount from Deribit trade response.
                Returns 0.0 if trade failed (error response or no result).
                """
                if not isinstance(resp, dict):
                    logger.warning(f"Invalid response type: {type(resp)}")
                    return 0.0

                # Check for error response - trade failed
                if "error" in resp:
                    logger.error(f"Trade failed with error: {resp.get('error')}")
                    return 0.0

                # Check for result - trade succeeded
                result = resp.get("result")
                if not result or not isinstance(result, dict):
                    logger.warning(f"No result in response: {resp}")
                    return 0.0

                order = result.get("order", {})
                if not order:
                    logger.warning(f"No order in result: {result}")
                    return 0.0

                # Try to get filled amount from various keys
                for key in ("filled_amount", "filledAmount", "amount_filled", "filled"):
                    val = order.get(key)
                    if val is not None:
                        try:
                            filled = float(val)
                            logger.info(f"Order filled: {filled} (key={key})")
                            return filled
                        except (TypeError, ValueError):
                            continue

                # Fallback: if we have a valid order but no filled key,
                # check if order_state indicates completion
                order_state = order.get("order_state", "")
                if order_state in ("filled", "closed"):
                    # Order completed, assume full fill
                    try:
                        filled = float(order.get("amount", default))
                        logger.info(f"Order state={order_state}, using amount: {filled}")
                        return filled
                    except (TypeError, ValueError):
                        pass

                logger.warning(f"Could not determine filled amount from order: {order}")
                return 0.0

            if strategy == 1:
                logger.info(f"Strategy 1: SELL {inst_k1}, BUY {inst_k2}, amount={amount}")
                r1 = await Deribit_trade.close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
                r2 = await Deribit_trade.open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
            elif strategy == 2:
                logger.info(f"Strategy 2: BUY {inst_k1}, SELL {inst_k2}, amount={amount}")
                r1 = await Deribit_trade.open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
                r2 = await Deribit_trade.close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
            else:
                raise ValueError("strategy must be 1 or 2")

            resps.extend([r1, r2])
            ids.extend([Deribit_trade.extract_order_id(r1), Deribit_trade.extract_order_id(r2)])

            filled1 = _filled_amount(r1, default=amount)
            filled2 = _filled_amount(r2, default=amount)
            logger.info(f"Vertical spread fills: leg1={filled1}, leg2={filled2}")

            # Critical error: both legs failed
            if filled1 == 0.0 and filled2 == 0.0:
                logger.error("CRITICAL: Both legs of vertical spread failed!")
                raise RuntimeError("Vertical spread execution failed: both legs returned 0 fill")

            # Warning: one leg failed completely
            if filled1 == 0.0 or filled2 == 0.0:
                logger.warning(f"One leg failed: filled1={filled1}, filled2={filled2}")

            matched_amount = min(filled1, filled2)
            executed_amount = matched_amount

            imbalance = filled1 - filled2
            if abs(imbalance) > 1e-8:
                logger.info(f"Rebalancing: imbalance={imbalance}, strategy={strategy}")
                if strategy == 1:
                    # leg1=sell(k1), leg2=buy(k2)
                    # imbalance > 0 means we sold more K1 than we bought K2
                    # Need to BUY K1 to reduce short position
                    if imbalance > 0:
                        logger.info(f"Rebalance: BUY {inst_k1} amount={imbalance}")
                        r_rebalance = await Deribit_trade.open_position(
                            websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                        )
                    else:
                        # imbalance < 0 means we bought more K2 than we sold K1
                        # Need to SELL K2 to reduce long position
                        logger.info(f"Rebalance: SELL {inst_k2} amount={abs(imbalance)}")
                        r_rebalance = await Deribit_trade.close_position(
                            websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                        )
                else:
                    # strategy 2: leg1=buy(k1), leg2=sell(k2)
                    # imbalance > 0 means we bought more K1 than we sold K2
                    # Need to SELL K1 to reduce long position
                    if imbalance > 0:
                        logger.info(f"Rebalance: SELL {inst_k1} amount={imbalance}")
                        r_rebalance = await Deribit_trade.close_position(
                            websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                        )
                    else:
                        # imbalance < 0 means we sold more K2 than we bought K1
                        # Need to BUY K2 to reduce short position
                        logger.info(f"Rebalance: BUY {inst_k2} amount={abs(imbalance)}")
                        r_rebalance = await Deribit_trade.open_position(
                            websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                        )

                resps.append(r_rebalance)
                ids.append(Deribit_trade.extract_order_id(r_rebalance))
                executed_amount = matched_amount
            else:
                logger.info(f"No rebalance needed: imbalance={imbalance}")

            return resps, ids, executed_amount
