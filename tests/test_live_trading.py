from __future__ import annotations

import asyncio
import csv
import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Tuple
import pprint

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    print("缺少 pydantic 依赖，请先运行 `pip install pydantic` 后再试。")
    sys.exit(1)

from src.utils.auth import ensure_signing_ready
from src.services.trade_service import RESULTS_CSV_HEADER, TradeApiError, execute_trade

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - FastAPI 可能未安装
    TestClient = None

SAMPLE_ROW_BASE: Dict[str, str] = {
    # 市场元数据（来源于 Polymarket 提供的 "Bitcoin above ___ on December 2?" 事件）
    "timestamp": "2025-12-01T11:52:46.916614Z",
    "market_title": "Will the price of Bitcoin be above $80,000 on December 2?",
    "asset": "BTC",
    "investment": "0",
    "selected_strategy": "1",
    "market_id": "bitcoin-above-80k-on-december-2",
    "pm_event_title": "Bitcoin above ___ on December 2?",
    "pm_market_title": "Will the price of Bitcoin be above $80,000 on December 2?",
    "pm_event_id": "bitcoin-above-on-december-2",
    "pm_market_id": "703579",
    "yes_token_id": "73598490064107318565005114994104398195344624125668078818829746637727926056405",
    "no_token_id": "7358660214941626459611817418274446092961130932038916619638865540777274288008",
    # 交易参数
    "inst_k1": "BTC-80k-YES",
    "inst_k2": "BTC-80k-NO",
    "spot": "80000",
    "poly_yes_price": "0.9725",
    "poly_no_price": "0.0275",
    "deribit_prob": "0.0",
    "K1": "80000",
    "K2": "80000",
    "K_poly": "80000",
    "T": "0.01",
    "days_to_expiry": "1",
    "sigma": "0.5",
    "r": "0.01",
    "k1_bid_btc": "0",
    "k1_ask_btc": "0",
    "k2_bid_btc": "0",
    "k2_ask_btc": "0",
    "k1_iv": "0",
    "k2_iv": "0",
    # 策略 1 (YES) / 策略 2 (NO) 的预期值与成本
    "net_ev_strategy1": "0",
    "gross_ev_strategy1": "0",
    "total_cost_strategy1": "0",
    "open_cost_strategy1": "0",
    "holding_cost_strategy1": "0",
    "close_cost_strategy1": "0",
    "contracts_strategy1": "0",
    "im_usd_strategy1": "0",
    "im_btc_strategy1": "0",
    "net_ev_strategy2": "0",
    "gross_ev_strategy2": "0",
    "total_cost_strategy2": "0",
    "open_cost_strategy2": "0",
    "holding_cost_strategy2": "0",
    "close_cost_strategy2": "0",
    "contracts_strategy2": "0",
    "im_usd_strategy2": "0",
    "im_btc_strategy2": "0",
    # 实际成交占位
    "avg_price_open_strategy1": "0",
    "avg_price_close_strategy1": "0",
    "shares_strategy1": "0",
    "avg_price_open_strategy2": "0",
    "avg_price_close_strategy2": "0",
    "shares_strategy2": "0",
    "slippage_open_strategy1": "0",
    "slippage_open_strategy2": "0",
}


def _write_csv(csv_path: Path, row: Dict[str, str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header_fields = set(RESULTS_CSV_HEADER.as_list())
    normalized_row = {k: v for k, v in row.items() if k in header_fields}
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_CSV_HEADER.as_list())
        writer.writeheader()
        writer.writerow(normalized_row)


def _prepare_row(clob_id: str, investment_usd: float) -> Tuple[str, Dict[str, str]]:
    market_id = f"manual-{clob_id}"
    row = {**SAMPLE_ROW_BASE}
    row.update(
        {
            "market_id": market_id,
            "yes_token_id": clob_id,
            "no_token_id": f"no-{clob_id}",
            "investment": str(investment_usd),
            "net_ev_strategy1": str(investment_usd * 0.05),
            "gross_ev_strategy1": str(investment_usd * 0.06),
            "total_cost_strategy1": str(investment_usd),
            "contracts_strategy1": "1.0",
        }
    )
    return market_id, row


def _is_live_enabled() -> bool:
    return true


def _run_execute_once(csv_path: Path, market_id: str, investment_usd: float, *, dry_run: bool) -> None:
    result, status, tx_id, message = asyncio.run(
        execute_trade(csv_path=str(csv_path), market_id=market_id, investment_usd=investment_usd, dry_run=dry_run)
    )
    print(
        "\n[execute_trade]",
        f"status={status}",
        f"tx_id={tx_id}",
        f"message={message}",
        f"direction={result.direction}",
        f"ev_usd={result.ev_usd}",
        f"contracts={result.contracts}",
        sep=" | ",
    )


def run_execute_trade(csv_path: Path, market_id: str, investment_usd: float, *, dry_run: bool) -> bool:
    """Run execute_trade once and optionally fall back to dry-run if live is blocked.

    Returns the *effective* dry_run value used for subsequent API tests.
    """

    try:
        _run_execute_once(csv_path, market_id, investment_usd, dry_run=dry_run)
        return dry_run
    except TradeApiError as exc:  # pragma: no cover - integration-facing message
        print("\n[execute_trade] 调用失败：", exc)
        if getattr(exc, "error_code", "") == "POLYMARKET_BLOCKED" and not dry_run:
            print(
                "Polymarket 拒绝请求（可能被 Cloudflare 拦截）。\n"
                "提示：检查 IP/VPN、Cookies、防爬限制，或在未解决前先用 dry-run 验证流程。\n"
                "将自动切换为 dry-run 再试一次……"
            )
            _run_execute_once(csv_path, market_id, investment_usd, dry_run=True)
            return True
        return dry_run


def run_api_post(csv_path: Path, market_id: str, investment_usd: float, *, dry_run: bool) -> None:
    if TestClient is None:
        print("\n[api/trade/execute] FastAPI 未安装，跳过接口调用")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        trading_config_path = Path(tmpdir) / "trading_config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "thresholds": {
                        "OUTPUT_CSV": str(csv_path),
                        "dry_trade": bool(dry_run),
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        trading_config_path.write_text("{}\n", encoding="utf-8")

        os.environ["CONFIG_PATH"] = str(config_path)
        os.environ["TRADING_CONFIG_PATH"] = str(trading_config_path)

        from src import api_server

        importlib.reload(api_server)
        client = TestClient(api_server.app)
        response = client.post(
            "/api/trade/execute",
            json={"market_id": market_id, "investment_usd": investment_usd, "dry_run": dry_run},
        )

    print("\n[POST /api/trade/execute] status=", response.status_code)
    try:
        pprint.pprint(response.json())
    except Exception:
        print("response text=", response.text)


def main() -> None:
    print("\n==== 使用说明 ====")
    print("1) 在终端复制运行：python src/test_live_trading.py")
    print("2) 按提示输入 Polymarket 的 CLOB id (yes_token_id) 与本次投入的 USD 金额。")
    print("3) 程序将先调用 execute_trade，再调用 /api/trade/execute 并打印结果。\n")

    clob_id = input("请输入要买的 CLOB id: ").strip()
    amount_raw = input("请输入投入的 USD 金额: ").strip()

    try:
        investment_usd = float(amount_raw)
    except ValueError:
        print("金额格式不正确，需为数字，例如 100 或 50.5")
        return

    market_id, row = _prepare_row(clob_id, investment_usd)
    dry_run = not _is_live_enabled()

    if not dry_run:
        status = ensure_signing_ready(require_token=True, log=False)
        print(f"[signer] {status}")

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "results.csv"
        _write_csv(csv_path, row)

        print("\n==== 开始交易测试 ====")
        print("当前模式：", "实盘" if not dry_run else "干跑 (dry-run)")
        effective_dry_run = run_execute_trade(csv_path, market_id, investment_usd, dry_run=dry_run)
        if effective_dry_run != dry_run:
            print("[execute_trade] 已切换为 dry-run 以继续接口测试")
        run_api_post(csv_path, market_id, investment_usd, dry_run=effective_dry_run)
        print("\n==== 测试结束 ====")


if __name__ == "__main__":  # pragma: no cover
    # main()
    pass