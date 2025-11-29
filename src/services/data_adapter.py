from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.save_result import ensure_csv_file
from .api_models import (
    DataFreshness,
    DBSnapshotResponse,
    DeribitStrikes,
    EVMarketData,
    EVMetrics,
    EVResponse,
    Opportunity,
    OptionCallData,
    OptionsData,
    PMOrderBook,
    PMOrderBookSide,
    PMSnapshotResponse,
    SpotPrice,
    VerticalSpread,
)

logger = logging.getLogger(__name__)


# ==========================
# Time helpers (epoch seconds)
# ==========================

def _parse_ts_to_epoch(ts: Optional[str]) -> int:
    """
    CSV timestamp is expected: "YYYY-MM-DD HH:MM:SS" (UTC)
    Fallback: now.
    """
    if not ts:
        return int(datetime.now(timezone.utc).timestamp())
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return int(datetime.now(timezone.utc).timestamp())


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _is_stale(last_updated_epoch: int, stale_after_seconds: int = 30) -> bool:
    return (_now_epoch() - last_updated_epoch) > stale_after_seconds


# ==========================
# Scalar helpers
# ==========================

def _safe_float(v: Any) -> Optional[float]:
    if v in (None, "", "NaN"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v in (None, "", "NaN"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ==========================
# CSV ingest
# ==========================

def _read_csv_rows(csv_path: str) -> List[Dict[str, Any]]:
    ensure_csv_file(csv_path)

    path = Path(csv_path)

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("Results CSV is empty")
    return rows


def _compute_market_id(row: Dict[str, Any]) -> str:
    asset = row.get("asset") or ""
    strike = _safe_int(row.get("K_poly") or row.get("strike"))
    return row.get("market_id") or (f"{asset}_{strike}" if asset and strike else "")


def _latest_rows_by_key(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    去重保留“最新快照”：按 (market_id, investment) 保留最新 timestamp。
    market_id 是我们对外的 market_id（例如 BTC_108000）。如果 CSV 没显式存，则由 asset + K_poly 推导。
    """
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        market_id = _compute_market_id(row)
        investment = row.get("investment") or ""
        key = (market_id, investment)

        prev = latest.get(key)
        if prev is None or (row.get("timestamp") or "") >= (prev.get("timestamp") or ""):
            latest[key] = row
    return list(latest.values())


def _pick_latest_row(rows: List[Dict[str, Any]], market_id: Optional[str] = None) -> Dict[str, Any]:
    """
    - market_id 为空：选全局最新 timestamp 的一行
    - market_id 非空：选该 market_id 下最新 timestamp 的一行
    """
    if market_id:
        rows = [r for r in rows if _compute_market_id(r) == market_id]
        if not rows:
            raise KeyError(f"market_id not found in csv: {market_id}")

    rows = sorted(rows, key=lambda r: (r.get("timestamp") or ""), reverse=True)
    return rows[0]


def _compute_expiry_date(row: Dict[str, Any]) -> Optional[str]:
    inst = row.get("inst_k1") or row.get("inst_k2") or ""
    # format: BTC-17NOV23-107000-C
    parts = inst.split("-")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return None


# ==========================
# 1) /api/pm schema adapter (Pydantic)
# ==========================

def load_pm_snapshot(csv_path: str, market_id: Optional[str] = None) -> PMSnapshotResponse:
    """
    Jo schema: single market snapshot
    """
    rows = _latest_rows_by_key(_read_csv_rows(csv_path))
    row = _pick_latest_row(rows, market_id=market_id)

    ts_epoch = _parse_ts_to_epoch(row.get("timestamp"))
    asset = row.get("asset") or ""
    strike = _safe_int(row.get("K_poly") or row.get("strike")) or 0
    out_market_id = _compute_market_id(row) or (market_id or "")

    yes_price = float(_safe_float(row.get("poly_yes_price")) or 0.0)
    no_price = float(_safe_float(row.get("poly_no_price")) or 0.0)

    # In your engine: strategy1 orderbook metrics correspond to YES token, strategy2 correspond to NO token.
    yes_side = PMOrderBookSide(
        bid=_safe_float(row.get("best_bid_strategy1")),
        ask=_safe_float(row.get("best_ask_strategy1")),
        mid=_safe_float(row.get("mid_price_strategy1")) or yes_price,
        spread=_safe_float(row.get("spread_strategy1")),
        liquidity_usd=0.0,
    )
    no_side = PMOrderBookSide(
        bid=_safe_float(row.get("best_bid_strategy2")),
        ask=_safe_float(row.get("best_ask_strategy2")),
        mid=_safe_float(row.get("mid_price_strategy2")) or no_price,
        spread=_safe_float(row.get("spread_strategy2")),
        liquidity_usd=0.0,
    )

    total_liq = float(yes_side.liquidity_usd + no_side.liquidity_usd)
    freshness = DataFreshness(stale=_is_stale(ts_epoch), last_updated=ts_epoch)

    return PMSnapshotResponse(
        timestamp=ts_epoch,
        market_id=out_market_id,
        event_title=row.get("pm_event_title") or row.get("event_title") or row.get("market_title"),
        asset=asset,
        strike=strike,
        yes_price=yes_price,
        no_price=no_price,
        orderbook=PMOrderBook(yes=yes_side, no=no_side),
        total_liquidity_usd=total_liq,
        last_trade_price=None,
        last_trade_time=None,
        data_freshness=freshness,
    )


# ==========================
# 2) /api/db schema adapter (Pydantic)
# ==========================

def load_db_snapshot(csv_path: str, market_id: Optional[str] = None) -> DBSnapshotResponse:
    """
    Jo schema: single market Deribit vertical spread snapshot
    """
    rows = _latest_rows_by_key(_read_csv_rows(csv_path))
    row = _pick_latest_row(rows, market_id=market_id)

    ts_epoch = _parse_ts_to_epoch(row.get("timestamp"))
    asset = row.get("asset") or ""
    strike = _safe_int(row.get("K_poly") or row.get("strike")) or 0
    out_market_id = _compute_market_id(row) or (market_id or "")

    k1 = _safe_int(row.get("K1")) or 0
    k2 = _safe_int(row.get("K2")) or 0
    spread_width = int(k2 - k1) if (k1 and k2) else None

    expiry = _compute_expiry_date(row)

    dte = _safe_float(row.get("days_to_expiry"))
    days_to_expiry = int(round(dte)) if dte is not None else None

    spot = float(_safe_float(row.get("spot")) or 0.0)

    # mark_price: not explicitly persisted; approximate with mid.
    k1_mid = float(_safe_float(row.get("k1_mid_btc")) or 0.0)
    k2_mid = float(_safe_float(row.get("k2_mid_btc")) or 0.0)

    k1_bid = _safe_float(row.get("k1_bid_btc"))
    k1_ask = _safe_float(row.get("k1_ask_btc"))
    k2_bid = _safe_float(row.get("k2_bid_btc"))
    k2_ask = _safe_float(row.get("k2_ask_btc"))

    k1_mark = k1_mid
    k2_mark = k2_mid

    mark_spread_btc = float(k1_mark - k2_mark)
    mid_spread_btc = float(k1_mid - k2_mid)
    mark_spread_usd = float(mark_spread_btc * spot)
    mid_spread_usd = float(mid_spread_btc * spot)

    dr_prob = _safe_float(row.get("deribit_prob"))

    strikes_model = DeribitStrikes(k1=k1, k2=k2, spread_width=spread_width)
    spot_model = SpotPrice(btc_usd=spot, source="deribit_index", last_updated=ts_epoch)

    options_model = OptionsData(
        k1_call=OptionCallData(
            instrument=row.get("inst_k1"),
            mark_price=k1_mark,
            mid_price=k1_mid,
            bid=k1_bid,
            ask=k1_ask,
            liquidity_btc=0.0,
        ),
        k2_call=OptionCallData(
            instrument=row.get("inst_k2"),
            mark_price=k2_mark,
            mid_price=k2_mid,
            bid=k2_bid,
            ask=k2_ask,
            liquidity_btc=0.0,
        ),
    )

    vertical_model = VerticalSpread(
        mark_spread_btc=mark_spread_btc,
        mid_spread_btc=mid_spread_btc,
        mark_spread_usd=mark_spread_usd,
        mid_spread_usd=mid_spread_usd,
        implied_probability=dr_prob,
    )

    freshness = DataFreshness(stale=_is_stale(ts_epoch), last_updated=ts_epoch)

    return DBSnapshotResponse(
        timestamp=ts_epoch,
        market_id=out_market_id,
        asset=asset,
        expiry_date=expiry,
        days_to_expiry=days_to_expiry,
        strikes=strikes_model,
        spot_price=spot_model,
        options_data=options_model,
        vertical_spread=vertical_model,
        data_freshness=freshness,
    )


# ==========================
# 3) /api/ev schema adapter (Pydantic)
# ==========================

def _chosen_net_ev(row: Dict[str, Any]) -> float:
    net1 = float(_safe_float(row.get("net_ev_strategy1")) or 0.0)
    net2 = float(_safe_float(row.get("net_ev_strategy2")) or 0.0)
    chosen = _safe_int(row.get("selected_strategy"))
    if chosen == 2:
        return net2
    if chosen == 1:
        return net1
    return net1 if net1 >= net2 else net2


def _ev_percentage(net_ev: float, investment: float) -> float:
    if investment <= 0:
        return 0.0
    return (net_ev / investment) * 100.0


def load_ev_snapshot(csv_path: str) -> EVResponse:
    """
    Jo schema: aggregate opportunities list ranked by ev_percentage based on investment=1000 row (closest).
    """
    rows = _latest_rows_by_key(_read_csv_rows(csv_path))

    by_market: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        mid = _compute_market_id(r)
        if not mid:
            continue
        by_market.setdefault(mid, []).append(r)

    def _pick_row_for_1000(rs: List[Dict[str, Any]]) -> Dict[str, Any]:
        # pick by |investment-1000| then timestamp desc
        def key(r: Dict[str, Any]):
            inv = _safe_float(r.get("investment")) or 0.0
            return (abs(inv - 1000.0), -_parse_ts_to_epoch(r.get("timestamp")))
        return sorted(rs, key=key)[0]

    opps: List[Opportunity] = []
    latest_ts = 0

    for mid, rs in by_market.items():
        r = _pick_row_for_1000(rs)

        ts_epoch = _parse_ts_to_epoch(r.get("timestamp"))
        if ts_epoch > latest_ts:
            latest_ts = ts_epoch

        asset = r.get("asset") or ""
        strike = _safe_int(r.get("K_poly") or r.get("strike")) or 0
        expiry = _compute_expiry_date(r)
        dte = _safe_float(r.get("days_to_expiry"))
        days_to_expiry = int(round(dte)) if dte is not None else None

        inv = float(_safe_float(r.get("investment")) or 1000.0)
        net = float(_chosen_net_ev(r))
        ev_pct = float(_ev_percentage(net, inv))

        pm_yes = float(_safe_float(r.get("poly_yes_price")) or 0.0)
        pm_no = float(_safe_float(r.get("poly_no_price")) or 0.0)
        dr_prob = float(_safe_float(r.get("deribit_prob")) or 0.0)
        divergence = float(pm_yes - dr_prob)

        # Filter later; rank later
        opps.append(
            Opportunity(
                market_id=mid,
                rank=0,
                asset=asset,
                strike=strike,
                expiry_date=expiry,
                days_to_expiry=days_to_expiry,
                ev_metrics=EVMetrics(ev_usd_1000=net, ev_percentage=ev_pct),
                market_data=EVMarketData(
                    pm_yes_price=pm_yes,
                    pm_no_price=pm_no,
                    dr_probability=dr_prob,
                    divergence=divergence,
                ),
            )
        )

    # opportunities: positive only
    opportunities = [o for o in opps if (o.ev_metrics.ev_usd_1000 > 0 and o.ev_metrics.ev_percentage > 0)]
    opportunities.sort(key=lambda o: o.ev_metrics.ev_percentage, reverse=True)

    for i, o in enumerate(opportunities, start=1):
        o.rank = i

    total = len(by_market)
    with_opp = len(opportunities)
    ts_epoch = latest_ts or _now_epoch()

    return EVResponse(
        timestamp=ts_epoch,
        total_markets_analyzed=total,
        markets_with_opportunities=with_opp,
        opportunities=opportunities,
    )


# ==========================
# Cache
# ==========================

@dataclass
class SnapshotCache:
    pm: PMSnapshotResponse | None = None
    db: DBSnapshotResponse | None = None
    ev: EVResponse | None = None
    last_refresh_epoch: int | None = None
    last_error: str | None = None


CACHE = SnapshotCache()


def refresh_cache(csv_path: str) -> SnapshotCache:
    """
    刷新缓存：默认取“最新市场”的 pm/db，以及全量 ev 机会列表。
    """
    try:
        CACHE.pm = load_pm_snapshot(csv_path)
        CACHE.db = load_db_snapshot(csv_path)
        CACHE.ev = load_ev_snapshot(csv_path)
        CACHE.last_refresh_epoch = _now_epoch()
        CACHE.last_error = None

        logger.info("refresh_cache ok csv=%s last_refresh=%s", csv_path, CACHE.last_refresh_epoch)
    except Exception as exc:
        CACHE.last_error = str(exc)
        logger.exception("refresh_cache failed: %s", exc)

    return CACHE
