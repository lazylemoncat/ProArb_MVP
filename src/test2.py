"""手动测试 Deribit（db）腿的双向交易脚本。

用途
----
当前的 `test_live_trading.py` 会优先尝试 Polymarket 下单；若该步骤失败，后续 Deribit
腿不会执行。此脚本用于单独验证 Deribit 垂直价差（牛市/熊市价差）下单流程，方便在
Polymarket 不可用时排查 Deribit 交易链路。

准备工作
--------
1. 环境变量中需提供 Deribit 认证信息：
   - ``deribit_user_id``
   - ``deribit_client_id``
   - ``deribit_client_secret``
   若设置了 ``DERIBIT_ENV_PREFIX``，则读取对应前缀的三项变量。
2. 如需真实下单，需将 ``ENABLE_LIVE_TRADING`` 设为 true/1/on/yes；未开启时将运行
   干跑（只打印计划，不会触发下单）。

输入项
------
运行 ``python src/test_db_trading.py`` 后依次输入：
1. **inst_k1**：Deribit 第一条腿的合约名称（例如 ``BTC-28JUN24-80000-C``）。
2. **inst_k2**：Deribit 第二条腿的合约名称。
3. **合约数量**：下单张数（浮点数）。
4. **策略方向**：输入 ``1`` 表示卖出价差（sell k1, buy k2），输入 ``2`` 表示买入价差
   （buy k1, sell k2）。

提示
----
- 本脚本不会触发 Polymarket 下单；只会调用 ``execute_vertical_spread`` 直接测试 Deribit
  双腿交易。
- 请确保网络和凭据可用后再开启实盘模式。
"""

from __future__ import annotations

import asyncio
import os
import pprint
import sys
from typing import List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
import json
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from websockets import ClientConnection
import websockets

WS_URL = "wss://www.deribit.com/ws/api/v2"
RPC_TIMEOUT_SEC = 10

os.environ["ENABLE_LIVE_TRADING"] = "true"

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


async def open_position(
    websocket: ClientConnection,
    deribitUserCfg: DeribitUserCfg,
    amount: float,
    instrument_name: str,
    type: str = "market",
) -> Dict[str, Any]:
    msg = {
        "id": str(deribitUserCfg.user_id),
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
        "id": str(deribitUserCfg.user_id),
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
    
async def get_margins(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg, instrument_name: str, amount, price):
    msg = {
        "id": str(deribitUserCfg.user_id),
        "jsonrpc":"2.0", 
        "method":"private/get_margins", 
        "params": {
            "amount": amount, 
            "instrument_name": instrument_name, 
            "price": price
        }
    }
    return await _send_rpc(websocket, msg)

async def get_positions(websocket: ClientConnection, deribitUserCfg: DeribitUserCfg):
    msg = {
        "id": str(deribitUserCfg.user_id),
        "jsonrpc": "2.0",
        "method": "private/get_positions",
        "params": {
            "currency": "BTC",
            "kind": "option"
        }
    }
    return await _send_rpc(websocket, msg)


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
        await deribit_websocket_auth(websocket, deribitUserCfg)

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
            r1 = await close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
            r2 = await open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
        elif strategy == 2:
            r1 = await open_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k1)
            r2 = await close_position(websocket, deribitUserCfg, amount=amount, instrument_name=inst_k2)
        else:
            raise ValueError("strategy must be 1 or 2")

        resps.extend([r1, r2])
        ids.extend([_extract_order_id(r1), _extract_order_id(r2)])

        filled1 = _filled_amount(r1, default=amount)
        filled2 = _filled_amount(r2, default=amount)
        matched_amount = min(filled1, filled2)
        executed_amount = matched_amount

        imbalance = filled1 - filled2
        if abs(imbalance) > 1e-8:
            if strategy == 1:
                # leg1=sell(k1), leg2=buy(k2)
                if imbalance > 0:
                    r_rebalance = await open_position(
                        websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                    )
                else:
                    r_rebalance = await close_position(
                        websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                    )
            else:
                # strategy 2: leg1=buy(k1), leg2=sell(k2)
                if imbalance > 0:
                    r_rebalance = await close_position(
                        websocket, deribitUserCfg, amount=imbalance, instrument_name=inst_k1
                    )
                else:
                    r_rebalance = await open_position(
                        websocket, deribitUserCfg, amount=abs(imbalance), instrument_name=inst_k2
                    )

            resps.append(r_rebalance)
            ids.append(_extract_order_id(r_rebalance))
            executed_amount = matched_amount

        return resps, ids, executed_amount


def _is_live_enabled() -> bool:
    return os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes", "on"}


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


def _print_responses(resps: List[dict], ids: List[Optional[str]], executed: float) -> None:
    print("\n=== Deribit 执行结果 ===")
    print("order_ids=", ids)
    print("executed_contracts=", executed)
    print("responses=")
    pprint.pprint(resps)


def run_deribit_spread(inst_k1: str, inst_k2: str, contracts: float, strategy: int, *, dry_run: bool) -> None:
    if strategy not in (1, 2):
        raise ValueError("strategy 需为 1 或 2")

    print("\n==== Deribit 交易参数 ====")
    print(f"inst_k1={inst_k1}")
    print(f"inst_k2={inst_k2}")
    print(f"contracts={contracts}")
    print(f"strategy={'卖出价差(1)' if strategy == 1 else '买入价差(2)'}")

    if dry_run:
        print("\n当前为干跑模式，不会向 Deribit 发送真实订单。")
        return

    cfg = _load_deribit_cfg()
    resps, ids, executed = asyncio.run(
        execute_vertical_spread(cfg, contracts=contracts, inst_k1=inst_k1, inst_k2=inst_k2, strategy=strategy)
    )
    _print_responses(resps, ids, executed)


def _prompt_float(label: str) -> float:
    raw = input(label).strip()
    try:
        return float(raw)
    except ValueError:
        print("输入格式不正确，需要数字。")
        sys.exit(1)

async def execute_single_leg_trade(
    deribitUserCfg: DeribitUserCfg,
    contracts: float,
    instrument_name: str,
    strategy: int,
) -> Tuple[List[Dict[str, Any]], List[Optional[str]], float]:
    """
    执行单腿操作：
      - strategy=1: 卖出合约（sell）
      - strategy=2: 买入合约（buy）

    返回 (responses, order_ids, executed_amount)
    """
    amount = float(contracts)

    async with websockets.connect(WS_URL) as websocket:
        await deribit_websocket_auth(websocket, deribitUserCfg)
        print(await get_positions(websocket, deribitUserCfg))
        print(await get_margins(websocket, deribitUserCfg, instrument_name, amount, 1000))
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

        if strategy == 1:  # 卖出
            r1 = await close_position(websocket, deribitUserCfg, amount=amount, instrument_name=instrument_name)
        elif strategy == 2:  # 买入
            r1 = await open_position(websocket, deribitUserCfg, amount=amount, instrument_name=instrument_name)
        else:
            raise ValueError("strategy must be 1 or 2")

        resps.append(r1)
        ids.append(_extract_order_id(r1))

        filled1 = _filled_amount(r1, default=amount)
        executed_amount = filled1

        return resps, ids, executed_amount

def run_single_leg_trade(inst_k1: str, contracts: float, strategy: int, *, dry_run: bool) -> None:
    if strategy not in (1, 2):
        raise ValueError("strategy 需为 1 或 2")

    print("\n==== Deribit 单腿交易 ====")
    print(f"inst_k1={inst_k1}")
    print(f"contracts={contracts}")
    print(f"strategy={'卖出(1)' if strategy == 1 else '买入(2)'}")

    if dry_run:
        print("\n当前为干跑模式，不会向 Deribit 发送真实订单。")
        return

    cfg = _load_deribit_cfg()
    resps, ids, executed = asyncio.run(
        execute_single_leg_trade(cfg, contracts=contracts, instrument_name=inst_k1, strategy=strategy)
    )
    _print_responses(resps, ids, executed)


def main() -> None:
    print("\n==== Deribit 单腿下单测试 ====")
    print("说明：本脚本仅用于测试 Deribit 单腿买入或卖出，不会调用 Polymarket。")

    inst_k1 = input("请输入 inst_k1（合约名）: ").strip()
    contracts = _prompt_float("请输入合约数量（支持小数）: ")
    strategy_raw = input("请选择策略方向（1=卖出, 2=买入）: ").strip()

    try:
        strategy = int(strategy_raw)
    except ValueError:
        print("策略方向需输入 1 或 2")
        return

    dry_run = not _is_live_enabled()
    print("当前模式：", "实盘" if not dry_run else "干跑 (dry-run)")

    try:
        run_single_leg_trade(inst_k1, contracts, strategy, dry_run=dry_run)
    except Exception as exc:  # pragma: no cover - 以易读格式打印错误
        print("\nDeribit 下单失败：", exc)


if __name__ == "__main__":  # pragma: no cover
    main()