from __future__ import annotations

import asyncio
import os
import pprint
import sys
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv

import json
from typing import Any, Dict, Tuple

import websockets
from websockets import ClientConnection

load_dotenv()
WS_URL = "wss://www.deribit.com/ws/api/v2"
RPC_TIMEOUT_SEC = 10


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

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> "DeribitUserCfg":
        config = cfg or {}
        try:
            return DeribitUserCfg(
                user_id=str(config["deribit_user_id"]),
                client_id=str(config["deribit_client_id"]),
                client_secret=str(config["deribit_client_secret"]),
            )
        except KeyError as exc:
            raise RuntimeError(
                "Missing deribit credentials in configuration (deribit_user_id/deribit_client_id/deribit_client_secret)"
            ) from exc
        

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
    await asyncio.wait_for(websocket.send(json.dumps(msg)), timeout=RPC_TIMEOUT_SEC)
    raw = await asyncio.wait_for(websocket.recv(), timeout=RPC_TIMEOUT_SEC)
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": str(raw)}


async def deribit_websocket_auth(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg) -> Dict[str, Any]:
    msg = {
        "id": str(deribitUserCfg.user_id),
        "jsonrpc": "2.0",
        "method": "public/auth",
        "params": {
            "client_id": deribitUserCfg.client_id,
            "client_secret": deribitUserCfg.client_secret,
            "grant_type": "client_credentials",
        },
    }
    return await _send_rpc(websocket, msg)

async def get_logs(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg):
    msg = {
        "id": str(deribitUserCfg.user_id), 
        "jsonrpc": "2.0", 
        "method": "private/get_transaction_log", 
        "params": {
            "count": 20,
            "currency": "BTC",
            "end_timestamp": "1765182765997", 
            "start_timestamp": "1765003785000"
        }
    }


    return await _send_rpc(websocket, msg)

async def logs(deribitUserCfg: DeribitUserCfg):
    async with websockets.connect(WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        return await get_logs(
            websocket=websocket,
            deribitUserCfg=deribitUserCfg,
        )
    
def _load_deribit_cfg() -> DeribitUserCfg:
    prefix = os.getenv("DERIBIT_ENV_PREFIX", "")
    try:
        return DeribitUserCfg.from_env(prefix=prefix)
    except Exception as exc:  # pragma: no cover - 提示凭证缺失
        print(
            "缺少 Deribit 认证信息，请确认已设置 deribit_user_id/deribit_client_id/deribit_client_secret。",
            f"当前 prefix='{prefix}'。",
        )
        raise
    
def main():
    cfg = _load_deribit_cfg()
    print(asyncio.run(logs(cfg)))

if __name__ == "__main__":
    main()