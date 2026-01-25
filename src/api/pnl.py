"""
PnL (Profit and Loss) API 端点

计算未实现盈亏，包含 Shadow View (策略逻辑) 和 Real View (物理现实) 的对比。
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

from .models import (
    PnlPositionDetail,
    PnlSummaryResponse,
    RealPosition,
    RealView,
    ShadowLeg,
    ShadowView,
)
from ..fetch_data.deribit.deribit_api import DeribitAPI
from ..fetch_data.polymarket.polymarket_api import PolymarketAPI
from ..utils.SqliteHandler import SqliteHandler
from ..core.save.save_position import SavePosition

logger = logging.getLogger(__name__)

pnl_router = APIRouter(tags=["pnl"])


def _safe_float(value, default: float = 0.0) -> float:
    """
    安全地将值转换为 float，处理 NaN/inf/None/空字符串等异常情况

    Args:
        value: 要转换的值
        default: 转换失败时的默认值

    Returns:
        有效的 float 值
    """
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _get_deribit_current_price(instrument_name: str) -> float:
    """
    获取 Deribit 合约的当前标记价格 (USD)

    Args:
        instrument_name: 合约名称 (e.g., "BTC-16JAN26-91000-C")

    Returns:
        当前标记价格 (USD)
    """
    try:
        ticker = DeribitAPI.get_ticker(instrument_name)
        mark_price_btc = _safe_float(ticker.get("mark_price", 0.0))
        # mark_price 是 BTC 计价，需要转换为 USD
        spot = _safe_float(DeribitAPI.get_spot_price("btc_usd"))
        return _safe_float(mark_price_btc * spot)
    except Exception as e:
        logger.warning(f"Failed to get ticker for {instrument_name}: {e}")
        return 0.0


def _get_pm_current_prices(market_id: str) -> tuple[float, float]:
    """
    获取 Polymarket 当前价格

    Args:
        market_id: PM 市场 ID

    Returns:
        (yes_price, no_price)
    """
    try:
        return PolymarketAPI.get_prices(market_id)
    except Exception as e:
        logger.warning(f"Failed to get PM prices for {market_id}: {e}")
        return 0.0, 0.0


def _calculate_position_pnl(row: dict, current_spot: float, price_cache: dict) -> PnlPositionDetail:
    """
    计算单个 position 的 PnL

    Args:
        row: positions 的一行数据
        current_spot: 当前 BTC 现货价格
        price_cache: 价格缓存 {instrument: price}

    Returns:
        PnlPositionDetail
    """
    signal_id = row.get("signal_id") or ""
    trade_id = row.get("trade_id") or ""
    timestamp = row.get("entry_timestamp") or ""
    market_title = row.get("market_title") or ""
    market_id = row.get("market_id") or ""

    # 入场数据 (使用 _safe_float 处理 NaN/inf)
    pm_entry_cost = _safe_float(row.get("pm_entry_cost", 0))
    dr_entry_cost = _safe_float(row.get("dr_entry_cost", 0))
    entry_price_pm = _safe_float(row.get("entry_price_pm", 0))
    entry_spot = _safe_float(row.get("spot", 0))
    contracts = _safe_float(row.get("contracts", 0))
    strategy = int(_safe_float(row.get("strategy", 2), 2))
    direction = (row.get("direction") or "").lower()

    # Deribit 合约信息
    inst_k1 = row.get("inst_k1") or ""
    inst_k2 = row.get("inst_k2") or ""
    dr_k1_price = _safe_float(row.get("dr_k1_price", 0))
    dr_k2_price = _safe_float(row.get("dr_k2_price", 0))

    # 开仓时 EV
    ev_usd = _safe_float(row.get("ev_model_usd", 0))

    # ========== 获取当前价格 ==========
    # Deribit 价格
    if inst_k1 not in price_cache:
        price_cache[inst_k1] = _get_deribit_current_price(inst_k1)
    if inst_k2 not in price_cache:
        price_cache[inst_k2] = _get_deribit_current_price(inst_k2)

    current_k1_price = price_cache.get(inst_k1, 0.0)
    current_k2_price = price_cache.get(inst_k2, 0.0)

    # PM 价格
    pm_cache_key = f"pm_{market_id}"
    if pm_cache_key not in price_cache:
        price_cache[pm_cache_key] = _get_pm_current_prices(market_id)
    current_yes_price, current_no_price = price_cache.get(pm_cache_key, (0.0, 0.0))

    # ========== Shadow View 计算 ==========
    # strategy=2: Long K1, Short K2
    # strategy=1: Short K1, Long K2
    shadow_legs = []

    if strategy == 2:
        # K1: Long (qty > 0)
        k1_qty = contracts
        k1_pnl = (current_k1_price - dr_k1_price) * k1_qty
        # K2: Short (qty < 0)
        k2_qty = -contracts
        k2_pnl = (dr_k2_price - current_k2_price) * contracts  # 空头盈亏 = (卖价 - 现价) * 数量
    else:  # strategy == 1
        # K1: Short (qty < 0)
        k1_qty = -contracts
        k1_pnl = (dr_k1_price - current_k1_price) * contracts
        # K2: Long (qty > 0)
        k2_qty = contracts
        k2_pnl = (current_k2_price - dr_k2_price) * k2_qty

    shadow_legs.append(ShadowLeg(
        instrument=inst_k1,
        qty=k1_qty,
        entry_price=dr_k1_price,
        current_price=current_k1_price,
        pnl=k1_pnl
    ))
    shadow_legs.append(ShadowLeg(
        instrument=inst_k2,
        qty=k2_qty,
        entry_price=dr_k2_price,
        current_price=current_k2_price,
        pnl=k2_pnl
    ))

    shadow_dr_pnl = k1_pnl + k2_pnl

    # ========== PM PnL 计算 ==========
    # 根据 direction 确定持有的是 YES 还是 NO
    pm_shares = _safe_float(row.get("pm_shares", 0))
    if pm_shares == 0 and entry_price_pm > 0:
        pm_shares = pm_entry_cost / entry_price_pm

    if direction == "no":
        # 持有 NO token
        entry_no_price = entry_price_pm
        current_pm_price = current_no_price
    else:
        # 持有 YES token
        entry_no_price = entry_price_pm
        current_pm_price = current_yes_price

    # PM PnL = (当前价格 - 入场价格) * 份数
    pm_pnl_usd = (current_pm_price - entry_price_pm) * pm_shares

    shadow_pnl_usd = shadow_dr_pnl + pm_pnl_usd

    shadow_view = ShadowView(
        pnl_usd=shadow_pnl_usd,
        legs=shadow_legs
    )

    # ========== Real View 计算 ==========
    # Real View 与 Shadow View 相同（对于单个 position）
    # 差异在汇总时体现 - 当多个 position 的同一合约会被 netting
    real_positions = []

    if k1_qty != 0:
        real_positions.append(RealPosition(
            instrument=inst_k1,
            qty=k1_qty,
            current_mark_price=current_k1_price
        ))
    if k2_qty != 0:
        real_positions.append(RealPosition(
            instrument=inst_k2,
            qty=k2_qty,
            current_mark_price=current_k2_price
        ))

    # Real PnL = Shadow PnL - early close fees (Deribit only)
    # 提前平仓手续费: 0.03% of underlying OR 0.125% of option value (取小)
    # 使用当前 mark price 计算平仓手续费
    delivery_fee_k1 = 0.0003 * current_spot * contracts  # 0.03% of underlying
    option_fee_k1 = 0.00125 * current_k1_price * contracts  # 0.125% of option value
    close_fee_k1 = min(delivery_fee_k1, option_fee_k1)

    delivery_fee_k2 = 0.0003 * current_spot * contracts
    option_fee_k2 = 0.00125 * current_k2_price * contracts
    close_fee_k2 = min(delivery_fee_k2, option_fee_k2)

    # 总平仓手续费 (两腿)
    close_fee_dr_usd = close_fee_k1 + close_fee_k2

    real_pnl_usd = shadow_pnl_usd - close_fee_dr_usd

    real_view = RealView(
        pnl_usd=real_pnl_usd,
        net_positions=real_positions
    )

    # ========== 币价波动 PnL ==========
    # currency_pnl = (current_spot - entry_spot) * btc_denominated_position
    # btc_denominated_position = contracts (Deribit 期权以 BTC 为单位)
    currency_pnl_usd = (current_spot - entry_spot) * contracts if entry_spot > 0 else 0.0

    # ========== 成本基础 ==========
    # 计算 Deribit 期权权利金（premium）
    # Strategy 2: Long K1 (pay dr_k1_price), Short K2 (receive dr_k2_price) -> net cost = dr_k1_price - dr_k2_price
    # Strategy 1: Short K1 (receive dr_k1_price), Long K2 (pay dr_k2_price) -> net cost = dr_k2_price - dr_k1_price
    if strategy == 2:
        option_premium_per_contract = dr_k1_price - dr_k2_price
    else:  # strategy == 1
        option_premium_per_contract = dr_k2_price - dr_k1_price

    option_premium_usd = option_premium_per_contract * contracts

    # cost_basis_usd = PM成本 + Deribit手续费 + Deribit权利金
    # 注意: dr_entry_cost 目前只包含手续费，所以需要加上权利金
    cost_basis_usd = pm_entry_cost + dr_entry_cost + option_premium_usd

    # ========== 汇总 ==========
    total_unrealized_pnl_usd = real_pnl_usd
    diff_usd = real_pnl_usd - shadow_pnl_usd

    # 残差校验: 理论上 diff 应该等于负的平仓手续费
    expected_diff = -close_fee_dr_usd
    residual_error_usd = diff_usd - expected_diff

    # 从 row 读取 funding_usd 和 im_value_usd (如果有)
    funding_usd = _safe_float(row.get("funding_usd", 0.0))
    im_value_usd = _safe_float(row.get("im_value_usd", 0.0))

    return PnlPositionDetail(
        signal_id=signal_id,
        timestamp=timestamp,
        market_title=market_title,
        funding_usd=funding_usd,
        cost_basis_usd=cost_basis_usd,
        total_unrealized_pnl_usd=total_unrealized_pnl_usd,
        im_value_usd=im_value_usd,
        shadow_view=shadow_view,
        real_view=real_view,
        pm_pnl_usd=pm_pnl_usd,
        fee_pm_usd=0.0,  # PM 无提前平仓手续费
        dr_pnl_usd=shadow_dr_pnl,
        fee_dr_usd=close_fee_dr_usd,  # Deribit 提前平仓手续费
        currency_pnl_usd=currency_pnl_usd,
        unrealized_pnl_usd=total_unrealized_pnl_usd,
        diff_usd=diff_usd,
        residual_error_usd=residual_error_usd,
        ev_usd=ev_usd,
        total_pnl_usd=total_unrealized_pnl_usd
    )


def _aggregate_real_view(position_details: list[PnlPositionDetail]) -> RealView:
    """
    聚合所有 position 的真实账本，计算净头寸

    同一 instrument 的头寸会被 netting:
    - position1: Long 93k-C (+1)
    - position2: Short 93k-C (-1)
    - 净头寸: 93k-C (0) -> 不显示
    """
    # 聚合净头寸
    net_positions: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "price": 0.0, "count": 0})

    for detail in position_details:
        for pos in detail.real_view.net_positions:
            net_positions[pos.instrument]["qty"] += pos.qty
            net_positions[pos.instrument]["price"] += pos.current_mark_price
            net_positions[pos.instrument]["count"] += 1

    # 构建 Real View
    real_positions = []
    total_real_pnl = 0.0

    for instrument, data in net_positions.items():
        net_qty = data["qty"]
        if abs(net_qty) < 1e-8:
            # 净头寸为 0，跳过
            continue

        avg_price = data["price"] / data["count"] if data["count"] > 0 else 0.0
        real_positions.append(RealPosition(
            instrument=instrument,
            qty=net_qty,
            current_mark_price=avg_price
        ))

    # Real PnL = 各 position 的 real_pnl 之和
    total_real_pnl = sum(d.real_view.pnl_usd for d in position_details)

    return RealView(
        pnl_usd=total_real_pnl,
        net_positions=real_positions
    )


def _aggregate_shadow_view(position_details: list[PnlPositionDetail]) -> ShadowView:
    """
    聚合所有 position 的影子账本 (保留所有腿，不做 netting)
    """
    all_legs = []
    total_shadow_pnl = 0.0

    for detail in position_details:
        all_legs.extend(detail.shadow_view.legs)
        total_shadow_pnl += detail.shadow_view.pnl_usd

    return ShadowView(
        pnl_usd=total_shadow_pnl,
        legs=all_legs
    )


def _build_pnl_where_clause(
    start_time: Optional[str],
    end_time: Optional[str],
    status: Optional[str]
) -> tuple[Optional[str], tuple]:
    """
    构建 SQLite WHERE 子句

    Args:
        start_time: 起始时间
        end_time: 结束时间
        status: 状态筛选

    Returns:
        (WHERE 子句, 参数元组)
    """
    conditions = []
    params = []

    if status:
        status_upper = status.strip().upper()
        if status_upper in ('OPEN', 'CLOSE'):
            conditions.append("UPPER(status) = ?")
            params.append(status_upper)

    if start_time:
        conditions.append("entry_timestamp >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("entry_timestamp <= ?")
        params.append(end_time)

    where_clause = " AND ".join(conditions) if conditions else None
    return where_clause, tuple(params)


@pnl_router.get("/api/pnl", response_model=PnlSummaryResponse)
def get_pnl_summary(
    start_time: Optional[str] = Query(default=None, description="起始时间 (ISO 格式, 如 2025-01-01T00:00:00Z)"),
    end_time: Optional[str] = Query(default=None, description="结束时间 (ISO 格式, 如 2025-01-01T23:59:59Z)"),
    status: Optional[str] = Query(default=None, description="仓位状态筛选: 'open' (未到期), 'close' (已到期), 或不传返回全部")
):
    """
    获取仓位的 PnL 汇总

    包含:
    - Shadow View: 策略逻辑视角，保留所有腿
    - Real View: 物理现实视角，聚合净头寸
    - 各项盈亏归因明细

    Args:
        start_time: 起始时间过滤 (ISO 格式, UTC)
        end_time: 结束时间过滤 (ISO 格式, UTC)
        status: 仓位状态筛选 ('open' 或 'close'，不传返回全部)

    Returns:
        PnL 汇总数据
    """
    now_str = datetime.now(timezone.utc).isoformat()

    # Build WHERE clause
    where_clause, params = _build_pnl_where_clause(start_time, end_time, status)

    # Query from SQLite
    rows = SqliteHandler.query_table(
        class_obj=SavePosition,
        where=where_clause,
        params=params,
        order_by="entry_timestamp DESC"
    )

    if not rows:
        return PnlSummaryResponse(
            timestamp=now_str,
            total_positions=0,
            total_cost_basis_usd=0.0,
            total_unrealized_pnl_usd=0.0,
            total_pm_pnl_usd=0.0,
            total_dr_pnl_usd=0.0,
            total_currency_pnl_usd=0.0,
            total_funding_usd=0.0,
            total_ev_usd=0.0,
            total_im_value_usd=0.0,
            shadow_view=ShadowView(pnl_usd=0.0, legs=[]),
            real_view=RealView(pnl_usd=0.0, net_positions=[]),
            diff_usd=0.0,
            positions=[]
        )

    # 获取当前 BTC 现货价格
    try:
        current_spot = DeribitAPI.get_spot_price("btc_usd")
    except Exception as e:
        logger.warning(f"Failed to get spot price: {e}")
        current_spot = 0.0

    # 价格缓存
    price_cache: dict = {}

    # 计算每个 position 的 PnL
    position_details: list[PnlPositionDetail] = []
    for row in rows:
        try:
            detail = _calculate_position_pnl(row, current_spot, price_cache)
            position_details.append(detail)
        except Exception as e:
            logger.error(f"Failed to calculate PnL for {row.get('trade_id')}: {e}", exc_info=True)
            continue

    # 汇总数据
    total_positions = len(position_details)
    total_cost_basis_usd = sum(d.cost_basis_usd for d in position_details)
    total_unrealized_pnl_usd = sum(d.total_unrealized_pnl_usd for d in position_details)
    total_pm_pnl_usd = sum(d.pm_pnl_usd for d in position_details)
    total_dr_pnl_usd = sum(d.dr_pnl_usd for d in position_details)
    total_currency_pnl_usd = sum(d.currency_pnl_usd for d in position_details)
    total_funding_usd = sum(d.funding_usd for d in position_details)
    total_ev_usd = sum(d.ev_usd for d in position_details)
    total_im_value_usd = sum(d.im_value_usd for d in position_details)

    # 聚合账本
    shadow_view = _aggregate_shadow_view(position_details)
    real_view = _aggregate_real_view(position_details)

    # 计算总差异
    diff_usd = real_view.pnl_usd - shadow_view.pnl_usd

    return PnlSummaryResponse(
        timestamp=now_str,
        total_positions=total_positions,
        total_cost_basis_usd=total_cost_basis_usd,
        total_unrealized_pnl_usd=total_unrealized_pnl_usd,
        total_pm_pnl_usd=total_pm_pnl_usd,
        total_dr_pnl_usd=total_dr_pnl_usd,
        total_currency_pnl_usd=total_currency_pnl_usd,
        total_funding_usd=total_funding_usd,
        total_ev_usd=total_ev_usd,
        total_im_value_usd=total_im_value_usd,
        shadow_view=shadow_view,
        real_view=real_view,
        diff_usd=diff_usd,
        positions=position_details
    )
