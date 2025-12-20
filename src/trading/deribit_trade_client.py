from typing import Any, Dict, List, Optional, Tuple

import websockets

from .deribit_trade import Deribit_trade, DeribitUserCfg

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
                order = resp.get("result", {}).get("order", {}) if isinstance(resp, dict) else {}
                for key in ("filled_amount", "filledAmount", "amount_filled", "filled"):
                    val = order.get(key)
                    if val is not None:
                        try:
                            return float(val)
                        except (TypeError, ValueError):
                            continue
                try:
                    return float(order.get("amount", default))
                except (TypeError, ValueError):
                    return default

            if strategy == 1:
                r1 = await Deribit_trade.close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
                r2 = await Deribit_trade.open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
            elif strategy == 2:
                r1 = await Deribit_trade.open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
                r2 = await Deribit_trade.close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
            else:
                raise ValueError("strategy must be 1 or 2")

            resps.extend([r1, r2])
            ids.extend([Deribit_trade.extract_order_id(r1), Deribit_trade.extract_order_id(r2)])

            filled1 = _filled_amount(r1, default=amount)
            filled2 = _filled_amount(r2, default=amount)
            matched_amount = min(filled1, filled2)
            executed_amount = matched_amount

            imbalance = filled1 - filled2
            if abs(imbalance) > 1e-8:
                if strategy == 1:
                    # leg1=sell(k1), leg2=buy(k2)
                    if imbalance > 0:
                        r_rebalance = await Deribit_trade.open_position(
                            websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                        )
                    else:
                        r_rebalance = await Deribit_trade.close_position(
                            websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                        )
                else:
                    # strategy 2: leg1=buy(k1), leg2=sell(k2)
                    if imbalance > 0:
                        r_rebalance = await Deribit_trade.close_position(
                            websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                        )
                    else:
                        r_rebalance = await Deribit_trade.open_position(
                            websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                        )

                resps.append(r_rebalance)
                ids.append(Deribit_trade.extract_order_id(r_rebalance))
                executed_amount = matched_amount

            return resps, ids, executed_amount
