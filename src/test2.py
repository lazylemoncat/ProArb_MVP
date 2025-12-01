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

from src.trading.deribit_trade import DeribitUserCfg, execute_vertical_spread
from dotenv import load_dotenv

load_dotenv()

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


def main() -> None:
    print("\n==== Deribit 双腿下单测试 ====")
    print("说明：本脚本仅用于测试 Deribit 交易链路，不会调用 Polymarket。")

    inst_k1 = input("请输入 inst_k1（第一条腿合约名）: ").strip()
    inst_k2 = input("请输入 inst_k2（第二条腿合约名）: ").strip()
    contracts = _prompt_float("请输入合约数量（支持小数）: ")
    strategy_raw = input("请选择策略方向（1=卖价差, 2=买价差）: ").strip()

    try:
        strategy = int(strategy_raw)
    except ValueError:
        print("策略方向需输入 1 或 2")
        return

    dry_run = not _is_live_enabled()
    print("当前模式：", "实盘" if not dry_run else "干跑 (dry-run)")

    try:
        run_deribit_spread(inst_k1, inst_k2, contracts, strategy, dry_run=dry_run)
    except Exception as exc:  # pragma: no cover - 以易读格式打印错误
        print("\nDeribit 下单失败：", exc)


if __name__ == "__main__":  # pragma: no cover
    main()