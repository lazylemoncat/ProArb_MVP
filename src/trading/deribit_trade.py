import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from websockets import ClientConnection

RPC_TIMEOUT_SEC = 10

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
            "id": int(deribitUserCfg.user_id),
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
            "id": int(deribitUserCfg.user_id),
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
            "id": int(deribitUserCfg.user_id),
            "jsonrpc": "2.0",
            "method": "private/buy",
            "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
        }
        return await Deribit_trade._send_rpc(websocket, msg)

    @staticmethod
    async def close_position(
        websocket: ClientConnection,
        deribitUserCfg: DeribitUserCfg,
        amount: float,
        instrument_name: str,
        type: str = "market",
    ) -> Dict[str, Any]:
        msg = {
            "id": int(deribitUserCfg.user_id),
            "jsonrpc": "2.0",
            "method": "private/sell",
            "params": {"amount": amount, "instrument_name": instrument_name, "type": type},
        }
        return await Deribit_trade._send_rpc(websocket, msg)