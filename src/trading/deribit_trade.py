import asyncio
import itertools
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from websockets import ClientConnection

logger = logging.getLogger(__name__)

RPC_TIMEOUT_SEC = 10

# Thread-safe counter for unique RPC message IDs
_rpc_id_counter = itertools.count(start=1)


def _next_rpc_id() -> int:
    """Generate a unique RPC message ID."""
    return next(_rpc_id_counter)


@dataclass
class DeribitUserCfg:
    user_id: str
    client_id: str
    client_secret: str


class Deribit_trade:
    @staticmethod
    async def get_orderbook_by_instrument_name(
        websocket: ClientConnection, 
        deribitUserCfg: DeribitUserCfg,
        instrument_name: str,
        depth: int
    ):
        msg = {
            "id": _next_rpc_id(),
            "jsonrpc": "2.0",
            "method": "public/get_order_book",
            "params": {
                "depth": depth,
                "instrument_name": instrument_name
            }
        }
        return await Deribit_trade._send_rpc(websocket, msg)
    
    @staticmethod
    def extract_order_id(obj: Any) -> Optional[str]:
        if obj is None:
            return None
        if isinstance(obj, dict):
            for k in ("order_id", "orderId", "orderID"):
                v = obj.get(k)
                if v:
                    return str(v)
            for v in obj.values():
                found = Deribit_trade.extract_order_id(v)
                if found:
                    return found
        if isinstance(obj, list):
            for v in obj:
                found = Deribit_trade.extract_order_id(v)
                if found:
                    return found
        return None

    @staticmethod
    async def _send_rpc(websocket: ClientConnection, msg: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.wait_for(websocket.send(json.dumps(msg)), timeout=RPC_TIMEOUT_SEC)
        raw = await asyncio.wait_for(websocket.recv(), timeout=RPC_TIMEOUT_SEC)
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": str(raw)}

    @staticmethod
    async def websocket_auth(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg) -> Dict[str, Any]:
        msg = {
            "id": _next_rpc_id(),
            "jsonrpc": "2.0",
            "method": "public/auth",
            "params": {
                "client_id": deribitUserCfg.client_id,
                "client_secret": deribitUserCfg.client_secret,
                "grant_type": "client_credentials",
            },
        }
        return await Deribit_trade._send_rpc(websocket, msg)

    @staticmethod
    async def open_position(
        websocket: ClientConnection,
        deribitUserCfg: DeribitUserCfg,
        amount: float,
        instrument_name: str,
        type: str = "market",
    ) -> Dict[str, Any]:
        msg = {
            "id": _next_rpc_id(),
            "jsonrpc": "2.0",
            "method": "private/buy",
            "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
        }
        resp = await Deribit_trade._send_rpc(websocket, msg)
        logger.info(f"Deribit BUY {instrument_name} amount={amount}: {resp}")
        return resp

    @staticmethod
    async def close_position(
        websocket: ClientConnection,
        deribitUserCfg: DeribitUserCfg,
        amount: float,
        instrument_name: str,
        type: str = "market",
    ) -> Dict[str, Any]:
        msg = {
            "id": _next_rpc_id(),
            "jsonrpc": "2.0",
            "method": "private/sell",
            "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
        }
        resp = await Deribit_trade._send_rpc(websocket, msg)
        logger.info(f"Deribit SELL {instrument_name} amount={amount}: {resp}")
        return resp