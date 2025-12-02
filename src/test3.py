"""Deribit testnet script for `private/get_margins`.

This utility authenticates with the Deribit testnet using client credentials
(read-only scope) and queries margins for a specified instrument, amount, and
price. It is intended for manual verification that read permissions are
working.

This version is ready to run without CLI arguments; adjust the constants below
if you want different values.

Environment variables
---------------------
- ``DERIBIT_ENV_PREFIX``: Optional prefix for credential env vars.
- ``deribit_user_id`` / ``deribit_client_id`` / ``deribit_client_secret``:
  Credentials for authentication (prefix honored).
- ``DERIBIT_TEST_WS_URL``: Override the testnet websocket URL if needed.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

import websockets
from dotenv import load_dotenv

from src.trading.deribit_trade import DeribitUserCfg

TEST_WS_URL = os.getenv("DERIBIT_TEST_WS_URL", "wss://www.deribit.com/ws/api/v2")

# Update these defaults in code if you need different values. No CLI input required.
DEFAULT_ENV_PREFIX = os.getenv("DERIBIT_ENV_PREFIX", "")
DEFAULT_SCOPE = "trade:read"
DEFAULT_INSTRUMENT = "BTC-2DEC25-87000-C"
DEFAULT_AMOUNT = 10_000.0
DEFAULT_PRICE = 3725.0


def _load_cfg(prefix: str) -> DeribitUserCfg:
    load_dotenv()
    return DeribitUserCfg.from_env(prefix=prefix)


def _build_auth_msg(cfg: DeribitUserCfg, *, scope: str) -> Dict[str, Any]:
    return {
        "id": int(cfg.user_id),
        "jsonrpc": "2.0",
        "method": "public/auth",
        "params": {
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        },
    }


def _build_margin_msg(cfg: DeribitUserCfg, *, instrument: str, amount: float, price: float) -> Dict[str, Any]:
    return {
        "id": int(cfg.user_id),
        "jsonrpc": "2.0",
        "method": "private/get_margins",
        "params": {"instrument_name": instrument, "amount": amount, "price": price},
    }


async def _send_rpc(websocket, msg: Dict[str, Any]) -> Dict[str, Any]:
    await websocket.send(json.dumps(msg))
    raw = await websocket.recv()
    return json.loads(raw)


async def run_margin_check(*, env_prefix: str, scope: str, instrument: str, amount: float, price: float) -> None:
    cfg = _load_cfg(env_prefix)
    async with websockets.connect(TEST_WS_URL) as websocket:
        auth_resp = await _send_rpc(websocket, _build_auth_msg(cfg, scope=scope))
        print("[auth]", json.dumps(auth_resp, ensure_ascii=False))

        if auth_resp.get("error"):
            return

        margin_resp = await _send_rpc(
            websocket,
            _build_margin_msg(cfg, instrument=instrument, amount=amount, price=price),
        )
        print("[margins]\n", json.dumps(margin_resp, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(
        run_margin_check(
            env_prefix=DEFAULT_ENV_PREFIX,
            scope=DEFAULT_SCOPE,
            instrument=DEFAULT_INSTRUMENT,
            amount=DEFAULT_AMOUNT,
            price=DEFAULT_PRICE,
        )
    )