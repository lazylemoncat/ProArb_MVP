import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from websockets import ClientConnection
import websockets

WS_URL = "wss://www.deribit.com/ws/api/v2"


@dataclass
class DeribitUserCfg:
    user_id: str
    client_id: str
    client_secret: str

    @staticmethod
    def from_env(prefix: str = "") -> "DeribitUserCfg":
        """
        默认读取 .env 中的：
          deribit_user_id / deribit_client_id / deribit_client_secret
        支持 prefix（例如 'test_'）。
        """
        def g(k: str) -> Optional[str]:
            return os.getenv(prefix + k) or os.getenv((prefix + k).upper())

        user_id = g("deribit_user_id")
        client_id = g("deribit_client_id")
        secret = g("deribit_client_secret")

        if not (user_id and client_id and secret):
            raise RuntimeError(
                f"Missing deribit env vars (prefix='{prefix}'): deribit_user_id/deribit_client_id/deribit_client_secret"
            )
        return DeribitUserCfg(user_id=str(user_id), client_id=str(client_id), client_secret=str(secret))


def _extract_order_id(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for k in ("order_id", "orderId", "orderID"):
            v = obj.get(k)
            if v:
                return str(v)
        for v in obj.values():
            found = _extract_order_id(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _extract_order_id(v)
            if found:
                return found
    return None


async def _send_rpc(websocket: ClientConnection, msg: Dict[str, Any]) -> Dict[str, Any]:
    await websocket.send(json.dumps(msg))
    raw = await websocket.recv()
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": str(raw)}


async def deribit_websocket_auth(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg) -> Dict[str, Any]:
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
    return await _send_rpc(websocket, msg)


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
    return await _send_rpc(websocket, msg)


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
    return await _send_rpc(websocket, msg)


async def buy(deribitUserCfg: DeribitUserCfg, amount: float, instrument_name: str) -> Dict[str, Any]:
    async with websockets.connect(WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        return await open_position(
            websocket=websocket,
            amount=amount,
            deribitUserCfg=deribitUserCfg,
            instrument_name=instrument_name,
        )


async def sell(deribitUserCfg: DeribitUserCfg, amount: float, instrument_name: str) -> Dict[str, Any]:
    async with websockets.connect(WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        return await close_position(
            websocket=websocket,
            amount=amount,
            deribitUserCfg=deribitUserCfg,
            instrument_name=instrument_name,
        )


async def execute_vertical_spread(
    deribitUserCfg: DeribitUserCfg,
    contracts: float,
    inst_k1: str,
    inst_k2: str,
    strategy: int,
) -> Tuple[List[Dict[str, Any]], List[Optional[str]]]:
    """
    执行两腿牛市价差：
      - strategy=1: 卖牛差（short K1, long K2） => sell k1, buy k2
      - strategy=2: 买牛差（long K1, short K2） => buy k1, sell k2

    返回 (responses, order_ids)
    """
    amount = float(contracts)

    async with websockets.connect(WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)

        resps: List[Dict[str, Any]] = []
        ids: List[Optional[str]] = []

        if strategy == 1:
            r1 = await close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
            r2 = await open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
        elif strategy == 2:
            r1 = await open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
            r2 = await close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
        else:
            raise ValueError("strategy must be 1 or 2")

        resps.extend([r1, r2])
        ids.extend([_extract_order_id(r1), _extract_order_id(r2)])

        return resps, ids
