from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..telegram.singleton import get_worker
from ..utils.dataloader import load_all_configs
from ..utils.save_result import RESULTS_CSV_HEADER, ensure_csv_file, save_position_to_csv

# trading executors (async)
from ..trading.deribit_trade import DeribitUserCfg
from ..trading.deribit_trade_client import Deribit_trade_client
from ..trading.polymarket_trade_client import Polymarket_trade_client
from .api_models import TradeResult

# ---------- errors ----------

class TradeApiError(Exception):
    def __init__(self, *, error_code: str, message: str, details: Dict[str, Any], status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code


logger = logging.getLogger(__name__)


_CONFIG_CACHE: Dict[str, Any] | None = None


def _get_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_all_configs()
    return _CONFIG_CACHE


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
    ensure_csv_file(csv_path, header=RESULTS_CSV_HEADER)

    path = Path(csv_path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        logger.warning("results csv has no rows: csv=%s", csv_path)
    return rows


def _build_manual_row(market_id: str, investment_usd: float) -> list[Dict[str, Any]] | None:
    """Allow trading when CSV is empty by using manual config overrides.

    Expected config keys under ``manual_trade``:
    - yes_token_id (required)
    - inst_k1 (required)
    - inst_k2 (required)
    - contracts (required; shared by both strategies)
    - no_token_id (optional; defaults to ``no-{yes_token_id}``)
    - poly_yes_price / poly_no_price / slippage_pct (optional)
    """

    cfg = _get_config()
    manual = cfg.get("manual_trade") or {}
    yes_token_id = manual.get("yes_token_id")
    inst_k1 = manual.get("inst_k1")
    inst_k2 = manual.get("inst_k2")
    contracts = _safe_float(manual.get("contracts") or manual.get("contracts_strategy1"), default=0.0)

    if not (yes_token_id and inst_k1 and inst_k2 and contracts and contracts > 0):
        logger.error("manual_trade config missing required fields; cannot build fallback row")
        return None

    no_token_id = manual.get("no_token_id") or f"no-{yes_token_id}"
    slippage = _safe_float(
        manual.get("slippage_rate_used")
        or manual.get("slippage_pct")
        or manual.get("slippage")
        or manual.get("slippage_rate"),
        default=0.0,
    )
    yes_price = _safe_float(
        manual.get("best_ask_strategy1")
        or manual.get("poly_yes_price")
        or manual.get("pm_yes_price")
        or manual.get("yes_price"),
        default=0.0,
    )
    no_price = _safe_float(
        manual.get("best_ask_strategy2")
        or manual.get("poly_no_price")
        or manual.get("pm_no_price")
        or manual.get("no_price"),
        default=0.0,
    )

    ts = datetime.now(timezone.utc).isoformat()
    row: Dict[str, Any] = {
        "timestamp": ts,
        "market_id": str(manual.get("market_id") or market_id or ""),
        "asset": str(manual.get("asset") or ""),
        "investment": str(investment_usd),
        "selected_strategy": str(manual.get("selected_strategy") or 1),
        "yes_token_id": str(yes_token_id),
        "no_token_id": str(no_token_id),
        "inst_k1": str(inst_k1),
        "inst_k2": str(inst_k2),
        "contracts_strategy1": str(contracts),
        "contracts_strategy2": str(manual.get("contracts_strategy2") or contracts),
        "im_usd_strategy1": str(manual.get("im_usd_strategy1") or 0.0),
        "im_usd_strategy2": str(manual.get("im_usd_strategy2") or 0.0),
        "im_btc_strategy1": str(manual.get("im_btc_strategy1") or 0.0),
        "im_btc_strategy2": str(manual.get("im_btc_strategy2") or 0.0),
        "best_ask_strategy1": str(yes_price),
        "best_ask_strategy2": str(no_price),
        "poly_yes_price": str(manual.get("poly_yes_price") or yes_price or 0.0),
        "poly_no_price": str(manual.get("poly_no_price") or no_price or 0.0),
        "slippage_rate_used": str(slippage),
    }

    logger.info("using manual_trade fallback row for market=%s", row["market_id"])
    return [row]


def _load_trade_rows(csv_path: str, market_id: str, investment_usd: float) -> list[Dict[str, Any]]:
    rows = _read_csv_rows(csv_path)
    if rows:
        return rows

    manual_rows = _build_manual_row(market_id, investment_usd)
    if manual_rows:
        return manual_rows

    raise TradeApiError(
        error_code="MISSING_DATA",
        message="Results CSV is empty and no manual trade fallback is configured",
        details={"csv_path": csv_path},
        status_code=503,
    )


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

    # net_profit_usd 返回的是 net_ev（即扣除成本后的净期望值）
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

    # 返回的字段需要区分 gross_ev 和 net_ev
    return TradeResult(
        direction=direction,  # "yes" / "no"
        ev_usd=float(gross),  # 确保返回的是 gross_ev
        roi_pct=float(roi_pct),
        total_cost_usd=float(total_cost),
        net_profit_usd=float(net_profit),  # 返回的是 net_ev
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
    rows = _load_trade_rows(csv_path, market_id, investment_usd)
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


async def execute_trade(*, csv_path: str, market_id: str, investment_usd: float, dry_run: bool, should_record_signal: bool) -> tuple[TradeResult, str, Optional[str], Optional[str]]:
    """
    返回 (result, status, tx_id, message)
    - dry_run=True: 仅 simulation，返回 status=DRY_RUN
    """
    if investment_usd <= 0:
        raise TradeApiError(
            error_code="INVALID_INVESTMENT",
            message="investment_usd must be > 0",
            details={"market_id": market_id, "investment_usd": investment_usd, "dry_run": dry_run},
            status_code=400,
        )

    rows = _load_trade_rows(csv_path, market_id, investment_usd)
    row = _pick_row_for_market_and_investment(rows, market_id, investment_usd)
    result = build_trade_result_from_row(row)

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

    config = _get_config()

    if dry_run:
        status = "DRY_RUN"
        tx_id = f"dryrun-{int(time.time())}"
        msg = "Trade executed in dry-run mode"
    else:
        pm_size = investment_usd / limit_price
        try:
            pm_resp, pm_order_id = Polymarket_trade_client.place_buy_by_investment(
                token_id=token_id, investment_usd=investment_usd, limit_price=limit_price
            )
        except Exception as exc:
            raise TradeApiError(
                error_code="EXECUTION_FAILED",
                message=f"Polymarket order failed: {exc}",
                details={
                    "stage": "polymarket",
                    "market_id": market_id,
                    "investment_usd": investment_usd,
                    "token_id": token_id,
                },
                status_code=502,
            )

        try:
            deribit_cfg = DeribitUserCfg(
                user_id=str(config["deribit_user_id"]),
                client_id=str(config["deribit_client_id"]),
                client_secret=str(config["deribit_client_secret"]),
            )
            sps, db_order_ids, executed_contracts = await Deribit_trade_client.execute_vertical_spread(
                deribit_cfg,
                contracts=contracts,
                inst_k1=inst_k1,
                inst_k2=inst_k2,
                strategy=strategy,
            )
        except Exception as exc:
            rollback_error = None
            try:
                rollback_resp, rollback_order_id = Polymarket_trade_client.place_sell_by_size(
                    token_id=token_id, size=pm_size, limit_price=0.999
                )
                logger.warning(
                    "Deribit leg failed after Polymarket execution; attempted rollback: order_id=%s resp=%s",
                    rollback_order_id,
                    rollback_resp,
                )
            except Exception as rb_exc:
                rollback_error = rb_exc
                logger.exception("Failed to rollback Polymarket position after Deribit failure")

            details = {
                "stage": "deribit",
                "market_id": market_id,
                "investment_usd": investment_usd,
                "inst_k1": inst_k1,
                "inst_k2": inst_k2,
            }
            if rollback_error:
                details["rollback_error"] = str(rollback_error)
            raise TradeApiError(
                error_code="EXECUTION_FAILED",
                message=f"Deribit execution failed: {exc}",
                details=details,
                status_code=502,
            )

        # 对实际成交数量进行对齐（处理Deribit部分成交）
        if executed_contracts is not None and executed_contracts < contracts:
            logger.warning(
                "Deribit partial fill detected: requested=%s, executed=%s", contracts, executed_contracts
            )
            result.contracts = float(executed_contracts)

        contracts = float(result.contracts)

        tx_id = f"pm:{pm_order_id or 'unknown'};db:{(db_order_ids[0] if db_order_ids else 'unknown')},{(db_order_ids[1] if len(db_order_ids)>1 else 'unknown')}"

        msg = f"Executed strategy={strategy} direction={result.direction} pm_limit={limit_price:.6f} contracts={contracts:.6f}, details:{pm_resp}"
        status = "EXECUTED"

    # 保存头寸信息到 CSV
    position_status = "DRY_RUN" if dry_run else "OPEN"

    # 从 row 提取完整的头寸信息
    k_poly = _safe_float(row.get("K_poly"), default=0.0)
    k1 = _safe_float(row.get("K1"), default=0.0)
    k2 = _safe_float(row.get("K2"), default=0.0)

    # 计算到期时间（从 Deribit 合约名解析或使用 days_to_expiry）
    days_to_expiry = _safe_float(row.get("days_to_expiry"), default=0.0)
    expiry_ts = int(time.time() * 1000 + days_to_expiry * 24 * 3600 * 1000)
    expiry_date = datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    # 计算 PM 入场成本和 DR 入场成本
    pm_entry_cost = investment_usd  # PM 端投入成本 = 投资金额
    # DR 入场成本 = Deribit 开仓费用（策略1卖牛差可能是净收入，策略2买牛差是净支出）
    dr_entry_cost = _safe_float(row.get(f"open_cost_strategy{strategy}"), default=0.0) - pm_entry_cost

    # 计算 PM token 数量
    pm_tokens = investment_usd / limit_price if limit_price > 0 else 0.0

    position_data = {
        # 基础信息
        "trade_id": tx_id,
        "market_id": market_id,
        "direction": result.direction,
        "strategy": strategy,
        "status": position_status,
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),

        # PM 头寸信息
        "pm_token_id": token_id,
        "pm_tokens": pm_tokens,
        "pm_entry_cost": pm_entry_cost,
        "entry_price_pm": limit_price,

        # DR 头寸信息
        "contracts": contracts,
        "dr_entry_cost": dr_entry_cost,
        "inst_k1": inst_k1,
        "inst_k2": inst_k2,

        # 行权价信息
        "K_poly": k_poly,
        "K1": k1,
        "K2": k2,

        # 资本信息
        "im_usd": result.im_usd,
        "capital_input": investment_usd + result.im_usd,

        # 到期信息
        "expiry_date": expiry_date,
        "expiry_timestamp": expiry_ts,

        # 平仓信息（开仓时为空）
        "exit_timestamp": "",
        "exit_price_pm": "",
        "settlement_price": "",
        "exit_pnl": "",
        "exit_reason": "",
    }

    save_position_to_csv(position_data)

    if should_record_signal:
        # --- Telegram: trade log (Bot2) ---
        try:
            tg = get_worker()

            asset = str(row.get("asset") or "")
            k_poly = _safe_float(row.get("K_poly"), default=0.0)
            market_title = f"{asset.upper()} > ${int(round(k_poly)):,}" if asset and k_poly else str(row.get("market_title") or market_id)

            # 从CSV读取正确的开仓成本（不包含投资本金）
            open_cost_fee_bucket = _safe_float(row.get(f"open_cost_strategy{strategy}"), default=0.0)

            # 注意：open_cost_fee_bucket 已经包含所有开仓费用：
            # - PM开仓成本: $0（滑点已包含在平均价中）
            # - Deribit开仓费: 手续费 + 滑点
            # - Gas费: 如果启用

            # 为了向后兼容，保留 fees_total 计算（但不再使用）
            slippage_rate = float(result.slippage_pct or 0.0)
            slippage_usd = float(investment_usd * slippage_rate)
            fees_total = max(0.0, float(open_cost_fee_bucket - slippage_usd))

            k1 = _safe_float(row.get("K1"), default=0.0)
            k2 = _safe_float(row.get("K2"), default=0.0)

            tg.publish({
                "type": "trade",
                "data": {
                    "action": "开仓",
                    "strategy": int(strategy),
                    "market_title": market_title,
                    "simulate": bool(dry_run),
                    "pm_side": "买入",
                    "pm_token": "YES" if strategy == 1 else "NO",
                    "pm_price": float(limit_price),          # 注意：这里用 limit_price 近似成交均价
                    "pm_amount_usd": float(investment_usd),
                    "deribit_action": "卖出牛差" if strategy == 1 else "买入牛差",
                    "deribit_k1": float(k1),
                    "deribit_k2": float(k2),
                    "deribit_contracts": float(contracts),
                    "fees_total": float(fees_total),
                    "slippage_usd": float(slippage_usd),
                    "open_cost": float(open_cost_fee_bucket),  # ✅ 修复：直接使用正确的开仓成本，不包含投资额
                    "margin_usd": float(result.im_usd),
                    "net_ev": float(result.net_profit_usd),
                    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "details": pm_resp
                }
            })
        except Exception as exc:
            # 发送失败不影响交易流程，但需要记录日志便于排查
            logger.warning("Failed to publish Telegram trade notification: %s", exc, exc_info=True)

    return result, status, tx_id, msg
