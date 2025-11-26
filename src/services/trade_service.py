from __future__ import annotations

import asyncio
import csv
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .api_models import TradeResult

# trading executors (async)
from ..trading.deribit_trade import DeribitUserCfg, execute_vertical_spread
from ..trading.polymarket_trade import place_buy_by_investment


# ---------- errors ----------

class TradeApiError(Exception):
    def __init__(self, *, error_code: str, message: str, details: Dict[str, Any], status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code


# ---------- helpers ----------

def _safe_float(v: Any, default: float = 0.0) -> float:
    if v in (None, "", "NaN"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any) -> Optional[int]:
    if v in (None, "", "NaN"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _compute_api_market_id(row: Dict[str, Any]) -> str:
    # Prefer explicit market_id in csv; otherwise derive from asset + K_poly/strike
    mid = row.get("market_id")
    if mid:
        return str(mid)
    asset = str(row.get("asset") or "")
    strike = _safe_int(row.get("K_poly") or row.get("strike") or row.get("K_poly_cfg"))
    return f"{asset}_{strike}" if (asset and strike is not None) else ""


def _read_csv_rows(csv_path: str) -> list[Dict[str, Any]]:
    path = Path(csv_path)
    if not path.exists():
        raise TradeApiError(
            error_code="MISSING_DATA",
            message=f"Results CSV not found at {csv_path}",
            details={"csv_path": csv_path},
            status_code=503,
        )
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise TradeApiError(
            error_code="MISSING_DATA",
            message="Results CSV is empty",
            details={"csv_path": csv_path},
            status_code=503,
        )
    return rows


def _pick_row_for_market_and_investment(rows: list[Dict[str, Any]], market_id: str, investment_usd: float) -> Dict[str, Any]:
    matches = [r for r in rows if _compute_api_market_id(r) == market_id]
    if not matches:
        raise TradeApiError(
            error_code="INVALID_MARKET",
            message=f"Market {market_id} not found",
            details={"market_id": market_id, "investment_usd": investment_usd},
            status_code=404,
        )

    # Pick the row with investment closest to requested; tie-break by newest timestamp string
    def key(r: Dict[str, Any]) -> Tuple[float, str]:
        inv = _safe_float(r.get("investment"), default=0.0)
        ts = str(r.get("timestamp") or "")
        return (abs(inv - investment_usd), f"{ts}")

    return sorted(matches, key=key)[0]


def _choose_strategy(row: Dict[str, Any]) -> int:
    chosen = _safe_int(row.get("selected_strategy"))
    if chosen in (1, 2):
        return int(chosen)

    net1 = _safe_float(row.get("net_ev_strategy1"), default=0.0)
    net2 = _safe_float(row.get("net_ev_strategy2"), default=0.0)
    return 1 if net1 >= net2 else 2


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_trade_result_from_row(row: Dict[str, Any]) -> TradeResult:
    """
    将 CSV 行映射为 trade result（用于 sim/execute）。
    约定：strategy1 => YES；strategy2 => NO
    """
    strategy = _choose_strategy(row)
    direction = "yes" if strategy == 1 else "no"

    gross = _safe_float(
        row.get(f"gross_ev_strategy{strategy}"),
        default=_safe_float(row.get(f"net_ev_strategy{strategy}"), 0.0),
    )
    total_cost = _safe_float(row.get(f"total_cost_strategy{strategy}"), default=0.0)
    net_profit = _safe_float(row.get(f"net_ev_strategy{strategy}"), default=(gross - total_cost))

    investment = _safe_float(row.get("investment"), default=0.0)
    roi_pct = (gross / investment * 100.0) if investment > 0 else 0.0

    im_usd = _safe_float(row.get(f"im_usd_strategy{strategy}"), default=0.0)
    im_btc = _safe_float(row.get(f"im_btc_strategy{strategy}"), default=0.0)
    contracts = _safe_float(row.get(f"contracts_strategy{strategy}"), default=0.0)

    # slippage pct: prefer unified rate; fallback to side-specific slippage
    slip = row.get("slippage_rate_used")
    if slip in (None, "", "NaN"):
        slip = row.get("pm_yes_slippage") if strategy == 1 else row.get("pm_no_slippage")
    slippage_pct = _safe_float(slip, default=0.0)

    return TradeResult(
        direction=direction,  # "yes" / "no"
        ev_usd=float(gross),
        roi_pct=float(roi_pct),
        total_cost_usd=float(total_cost),
        net_profit_usd=float(net_profit),
        im_usd=float(im_usd),
        im_btc=float(im_btc),
        contracts=float(contracts),
        slippage_pct=float(slippage_pct),
    )


def simulate_trade(*, csv_path: str, market_id: str, investment_usd: float) -> TradeResult:
    if investment_usd <= 0:
        raise TradeApiError(
            error_code="INVALID_INVESTMENT",
            message="investment_usd must be > 0",
            details={"market_id": market_id, "investment_usd": investment_usd},
            status_code=400,
        )
    rows = _read_csv_rows(csv_path)
    row = _pick_row_for_market_and_investment(rows, market_id, investment_usd)
    return build_trade_result_from_row(row)


def _require_cols(row: Dict[str, Any], cols: list[str], *, market_id: str, investment_usd: float) -> None:
    missing = [c for c in cols if not row.get(c)]
    if missing:
        raise TradeApiError(
            error_code="MISSING_EXECUTION_FIELDS",
            message="CSV is missing required execution columns",
            details={"market_id": market_id, "investment_usd": investment_usd, "missing": missing},
            status_code=503,
        )


async def execute_trade(*, csv_path: str, market_id: str, investment_usd: float, dry_run: bool) -> tuple[TradeResult, str, Optional[str], Optional[str]]:
    """
    返回 (result, status, tx_id, message)
    - dry_run=True: 仅 simulation，返回 status=DRY_RUN
    - dry_run=False: 真实执行（需 ENABLE_LIVE_TRADING=true）
    """
    if investment_usd <= 0:
        raise TradeApiError(
            error_code="INVALID_INVESTMENT",
            message="investment_usd must be > 0",
            details={"market_id": market_id, "investment_usd": investment_usd, "dry_run": dry_run},
            status_code=400,
        )

    rows = _read_csv_rows(csv_path)
    row = _pick_row_for_market_and_investment(rows, market_id, investment_usd)
    result = build_trade_result_from_row(row)

    if dry_run:
        return result, "DRY_RUN", f"dryrun-{int(time.time())}", "Trade executed in dry-run mode"

    # 安全阀：默认禁止真实交易
    if os.getenv("ENABLE_LIVE_TRADING", "false").lower() not in ("1", "true", "yes", "on"):
        raise TradeApiError(
            error_code="EXECUTION_DISABLED",
            message="Real execution is disabled. Set ENABLE_LIVE_TRADING=true to enable.",
            details={"market_id": market_id, "investment_usd": investment_usd, "dry_run": dry_run},
            status_code=501,
        )

    strategy = _choose_strategy(row)

    # 需要 CSV 中包含用于下单的 token/instrument 字段
    _require_cols(
        row,
        cols=["yes_token_id", "no_token_id", "inst_k1", "inst_k2"],
        market_id=market_id,
        investment_usd=investment_usd,
    )

    # ----- Polymarket order -----
    token_id = str(row["yes_token_id"] if strategy == 1 else row["no_token_id"])
    best_ask = _safe_float(row.get(f"best_ask_strategy{strategy}"), default=_safe_float(row.get("poly_yes_price" if strategy == 1 else "poly_no_price"), 0.0))
    slippage = float(result.slippage_pct)
    limit_price = _clamp(best_ask * (1.0 + slippage), 0.001, 0.999)

    try:
        pm_resp, pm_order_id = place_buy_by_investment(token_id=token_id, investment_usd=investment_usd, limit_price=limit_price)
    except Exception as exc:
        raise TradeApiError(
            error_code="EXECUTION_FAILED",
            message=f"Polymarket order failed: {exc}",
            details={"stage": "polymarket", "market_id": market_id, "investment_usd": investment_usd, "token_id": token_id},
            status_code=502,
        )

    # ----- Deribit spread -----
    inst_k1 = str(row["inst_k1"])
    inst_k2 = str(row["inst_k2"])
    contracts = _safe_float(row.get(f"contracts_strategy{strategy}"), default=0.0)
    if contracts <= 0:
        raise TradeApiError(
            error_code="INVALID_CONTRACTS",
            message="contracts computed <= 0, cannot execute",
            details={"market_id": market_id, "investment_usd": investment_usd, "contracts": contracts, "strategy": strategy},
            status_code=503,
        )

    try:
        deribit_cfg = DeribitUserCfg.from_env(prefix=os.getenv("DERIBIT_ENV_PREFIX", ""))
        db_resps, db_order_ids = await execute_vertical_spread(
            deribit_cfg,
            contracts=contracts,
            inst_k1=inst_k1,
            inst_k2=inst_k2,
            strategy=strategy,
        )
    except Exception as exc:
        raise TradeApiError(
            error_code="EXECUTION_FAILED",
            message=f"Deribit execution failed: {exc}",
            details={"stage": "deribit", "market_id": market_id, "investment_usd": investment_usd, "inst_k1": inst_k1, "inst_k2": inst_k2},
            status_code=502,
        )

    tx_id = f"pm:{pm_order_id or 'unknown'};db:{(db_order_ids[0] if db_order_ids else 'unknown')},{(db_order_ids[1] if len(db_order_ids)>1 else 'unknown')}"

    msg = f"Executed strategy={strategy} direction={result.direction} pm_limit={limit_price:.6f} contracts={contracts:.6f}"
    return result, "EXECUTED", tx_id, msg
