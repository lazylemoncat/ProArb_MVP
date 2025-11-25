# src/api_server.py
from __future__ import annotations

import os
import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, HTTPException

from .utils.dataloader import load_manual_data

app = FastAPI(title="Deribit x Polymarket Arbitrage API")

# 允许通过环境变量指定 config 路径，默认仍然是 config.yaml
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")
_CONFIG_CACHE: Dict[str, Any] | None = None


def _get_config() -> Dict[str, Any]:
    """懒加载配置，避免每个请求都重新读 config.yaml。"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_manual_data(CONFIG_PATH)
    return _CONFIG_CACHE


def _get_csv_path() -> str:
    """
    从配置中获取结果 CSV 路径：
      config['thresholds']['OUTPUT_CSV']
    若缺失则退回到 save_result_csv 的默认路径 data/results.csv。
    """
    cfg = _get_config()
    thresholds = cfg.get("thresholds") or {}
    return thresholds.get("OUTPUT_CSV", "data/results.csv")


def _load_latest_rows() -> List[Dict[str, Any]]:
    """
    读取结果 CSV，并按 (market_title, investment) 保留最新一条。
    这样一个市场在不同投资档位上各保留一条最新记录。
    """
    csv_path = _get_csv_path()
    path = Path(csv_path)

    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Results CSV not found: {csv_path}",
        )

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise HTTPException(
            status_code=503,
            detail="Results CSV is empty",
        )

    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in rows:
        market_title = row.get("market_title") or ""
        investment = row.get("investment") or ""
        key = (market_title, investment)
        prev = latest.get(key)
        # timestamp 格式为 "YYYY-MM-DD HH:MM:SS"，字符串比较就是时间顺序
        if prev is None or (row.get("timestamp") or "") >= (prev.get("timestamp") or ""):
            latest[key] = row

    return list(latest.values())


def _parse_float(row: Dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v in (None, "", "NaN"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_int(row: Dict[str, Any], key: str) -> int | None:
    v = row.get(key)
    if v in (None, "", "NaN"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _row_to_struct(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    把 CSV 的一行整理成结构化的字典：
      - 基本信息
      - pm: Polymarket 相关字段
      - deribit: Deribit 相关字段
      - ev: EV 和成本相关字段

    所有字段都来自 InvestmentResult.to_csv_row 写入的列。:contentReference[oaicite:6]{index=6}
    """
    base = {
        "timestamp": row.get("timestamp"),
        "market_title": row.get("market_title"),
        "asset": row.get("asset"),
        "investment": _parse_float(row, "investment"),
        "selected_strategy": _parse_int(row, "selected_strategy"),
    }

    pm = {
        "yes_price": _parse_float(row, "poly_yes_price"),
        "no_price": _parse_float(row, "poly_no_price"),
        "best_ask_strategy1": _parse_float(row, "best_ask_strategy1"),
        "best_bid_strategy1": _parse_float(row, "best_bid_strategy1"),
        "mid_price_strategy1": _parse_float(row, "mid_price_strategy1"),
        "spread_strategy1": _parse_float(row, "spread_strategy1"),
        "best_ask_strategy2": _parse_float(row, "best_ask_strategy2"),
        "best_bid_strategy2": _parse_float(row, "best_bid_strategy2"),
        "mid_price_strategy2": _parse_float(row, "mid_price_strategy2"),
        "spread_strategy2": _parse_float(row, "spread_strategy2"),
    }

    deribit = {
        "spot": _parse_float(row, "spot"),
        "deribit_prob": _parse_float(row, "deribit_prob"),
        "K1": _parse_float(row, "K1"),
        "K2": _parse_float(row, "K2"),
        "K_poly": _parse_float(row, "K_poly"),
        "T": _parse_float(row, "T"),
        "days_to_expiry": _parse_float(row, "days_to_expiry"),
        "sigma": _parse_float(row, "sigma"),
        "r": _parse_float(row, "r"),
        "k1_bid_btc": _parse_float(row, "k1_bid_btc"),
        "k1_ask_btc": _parse_float(row, "k1_ask_btc"),
        "k2_bid_btc": _parse_float(row, "k2_bid_btc"),
        "k2_ask_btc": _parse_float(row, "k2_ask_btc"),
        "im_usd": _parse_float(row, "im_usd"),
        "im_btc": _parse_float(row, "im_btc"),
        "im_usd_strategy1": _parse_float(row, "im_usd_strategy1"),
        "im_usd_strategy2": _parse_float(row, "im_usd_strategy2"),
        "im_btc_strategy1": _parse_float(row, "im_btc_strategy1"),
        "im_btc_strategy2": _parse_float(row, "im_btc_strategy2"),
    }

    ev = {
        "net_ev_strategy1": _parse_float(row, "net_ev_strategy1"),
        "net_ev_strategy2": _parse_float(row, "net_ev_strategy2"),
        "gross_ev_strategy1": _parse_float(row, "gross_ev_strategy1"),
        "gross_ev_strategy2": _parse_float(row, "gross_ev_strategy2"),
        "total_cost_strategy1": _parse_float(row, "total_cost_strategy1"),
        "total_cost_strategy2": _parse_float(row, "total_cost_strategy2"),
        "open_cost_strategy1": _parse_float(row, "open_cost_strategy1"),
        "open_cost_strategy2": _parse_float(row, "open_cost_strategy2"),
        "holding_cost_strategy1": _parse_float(row, "holding_cost_strategy1"),
        "holding_cost_strategy2": _parse_float(row, "holding_cost_strategy2"),
        "close_cost_strategy1": _parse_float(row, "close_cost_strategy1"),
        "close_cost_strategy2": _parse_float(row, "close_cost_strategy2"),
    }

    return {**base, "pm": pm, "deribit": deribit, "ev": ev}


@app.get("/health")
async def health() -> Dict[str, Any]:
    """健康检查端点，用于探活。"""
    return {"status": "ok"}


@app.get("/api/markets")
async def api_markets() -> Dict[str, Any]:
    """
    整合视图：返回每个 (market_title, investment) 最新的一条记录，
    内含 pm + deribit + ev 三大块。
    """
    rows = _load_latest_rows()
    markets = [_row_to_struct(r) for r in rows]
    return {"markets": markets}


@app.get("/api/pm")
async def api_pm_snapshot() -> Dict[str, Any]:
    """
    /api/pm → 返回当前各市场（按 investment 维度拆分）的 Polymarket 快照 + 相关信息。
    数据来自监控进程写入的 CSV，而不是直接连 Polymarket。:contentReference[oaicite:7]{index=7}
    """
    rows = _load_latest_rows()
    markets = []

    for r in rows:
        s = _row_to_struct(r)
        markets.append(
            {
                "timestamp": s["timestamp"],
                "market_title": s["market_title"],
                "asset": s["asset"],
                "investment": s["investment"],
                "selected_strategy": s["selected_strategy"],
                "pm": s["pm"],
            }
        )

    return {"markets": markets}


@app.get("/api/dr")
async def api_dr_snapshot() -> Dict[str, Any]:
    """
    /api/dr → 返回当前各市场（按 investment 维度拆分）的 Deribit 行情快照 + 保证金信息。
    数据来自监控进程写入的 CSV。
    """
    rows = _load_latest_rows()
    markets = []

    for r in rows:
        s = _row_to_struct(r)
        markets.append(
            {
                "timestamp": s["timestamp"],
                "market_title": s["market_title"],
                "asset": s["asset"],
                "investment": s["investment"],
                "selected_strategy": s["selected_strategy"],
                "deribit": s["deribit"],
            }
        )

    return {"markets": markets}


@app.get("/api/ev")
async def api_ev_snapshot() -> Dict[str, Any]:
    """
    /api/ev → 返回当前各市场（按 investment 维度拆分）的 EV 结果和成本分解。
    包含：
      - net_ev_strategy1 / net_ev_strategy2
      - gross_ev_strategy1 / gross_ev_strategy2
      - open/holding/close/total_cost_strategy1/2
    """
    rows = _load_latest_rows()
    markets = []

    for r in rows:
        s = _row_to_struct(r)
        markets.append(
            {
                "timestamp": s["timestamp"],
                "market_title": s["market_title"],
                "asset": s["asset"],
                "investment": s["investment"],
                "selected_strategy": s["selected_strategy"],
                "ev": s["ev"],
            }
        )

    return {"markets": markets}
