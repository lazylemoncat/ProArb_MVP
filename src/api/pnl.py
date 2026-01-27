"""
PnL (Profit and Loss) API 端点

计算未实现盈亏，包含 Shadow View (策略逻辑) 和 Real View (物理现实) 的对比。
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, BackgroundTasks
from pydantic import BaseModel

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


def _safe_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    """
    安全地将值转换为 float，处理 NaN/inf/None/空字符串等异常情况

    Args:
        value: 要转换的值
        default: 转换失败时的默认值，可以为 None

    Returns:
        有效的 float 值，或 default（可能为 None）
    """
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _get_deribit_current_price(instrument_name: str) -> Optional[float]:
    """
    获取 Deribit 合约的当前标记价格 (USD)

    Args:
        instrument_name: 合约名称 (e.g., "BTC-16JAN26-91000-C")

    Returns:
        当前标记价格 (USD)，获取失败时返回 None
    """
    try:
        ticker = DeribitAPI.get_ticker(instrument_name)
        mark_price_btc = ticker.get("mark_price")
        if mark_price_btc is None:
            logger.warning(f"No mark_price in ticker for {instrument_name}")
            return None
        mark_price_btc = _safe_float(mark_price_btc, default=None)
        if mark_price_btc is None:
            return None
        # mark_price 是 BTC 计价，需要转换为 USD
        spot = DeribitAPI.get_spot_price("btc_usd")
        if spot is None:
            logger.warning(f"Failed to get spot price for {instrument_name}")
            return None
        spot = _safe_float(spot, default=None)
        if spot is None:
            return None
        return _safe_float(mark_price_btc * spot, default=None)
    except Exception as e:
        logger.warning(f"Failed to get ticker for {instrument_name}: {e}")
        return None


def _get_pm_current_prices(market_id: str) -> tuple[Optional[float], Optional[float]]:
    """
    获取 Polymarket 当前价格

    Args:
        market_id: PM 市场 ID

    Returns:
        (yes_price, no_price)，获取失败时返回 (None, None)
    """
    try:
        yes_price, no_price = PolymarketAPI.get_prices(market_id)
        # 验证返回值是否有效
        yes_price = _safe_float(yes_price, default=None)
        no_price = _safe_float(no_price, default=None)
        return yes_price, no_price
    except Exception as e:
        logger.warning(f"Failed to get PM prices for {market_id}: {e}")
        return None, None


def _calculate_position_pnl(row: dict, current_spot: Optional[float], price_cache: dict) -> Optional[PnlPositionDetail]:
    """
    计算单个 position 的 PnL

    Args:
        row: positions 的一行数据
        current_spot: 当前 BTC 现货价格，可能为 None
        price_cache: 价格缓存 {instrument: price}

    Returns:
        PnlPositionDetail，如果价格获取失败则返回 None
    """
    signal_id = row.get("signal_id") or ""
    trade_id = row.get("trade_id") or ""
    timestamp = row.get("entry_timestamp") or ""
    market_title = row.get("market_title") or ""
    market_id = row.get("market_id") or ""
    status = (row.get("status") or "").upper()

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
    # 根据仓位状态决定使用结算价格还是实时价格
    if status == "CLOSE":
        # 已平仓位：使用数据库中的结算价格，不调用 API
        # Deribit 结算价格已经是 USD 计价
        current_k1_price = _safe_float(row.get("k1_settlement_price"), default=None)
        current_k2_price = _safe_float(row.get("k2_settlement_price"), default=None)

        # PM 结算价格
        current_yes_price = _safe_float(row.get("pm_yes_settlement_price"), default=None)
        current_no_price = _safe_float(row.get("pm_no_settlement_price"), default=None)

        # 结算时的现货价格（使用 settlement_index_price 如果有，否则用入场时的 spot）
        settlement_spot = _safe_float(row.get("settlement_index_price"), default=None)
        if settlement_spot is not None:
            current_spot = settlement_spot
        elif current_spot is None:
            # 回退到入场时的 spot
            current_spot = entry_spot

        # 检查结算价格是否有效
        if current_k1_price is None or current_k2_price is None:
            logger.warning(f"Skipping closed position {signal_id}: Deribit settlement price unavailable "
                          f"(k1={current_k1_price}, k2={current_k2_price})")
            return None

        if current_yes_price is None or current_no_price is None:
            logger.warning(f"Skipping closed position {signal_id}: PM settlement price unavailable "
                          f"(yes={current_yes_price}, no={current_no_price})")
            return None
    else:
        # 开仓位：正常获取实时价格
        # Deribit 价格
        if inst_k1 not in price_cache:
            price_cache[inst_k1] = _get_deribit_current_price(inst_k1)
        if inst_k2 not in price_cache:
            price_cache[inst_k2] = _get_deribit_current_price(inst_k2)

        current_k1_price = price_cache.get(inst_k1)
        current_k2_price = price_cache.get(inst_k2)

        # 检查 Deribit 价格是否有效
        if current_k1_price is None or current_k2_price is None:
            logger.warning(f"Skipping position {signal_id}: Deribit price unavailable "
                          f"(k1={current_k1_price}, k2={current_k2_price})")
            return None

        # PM 价格
        pm_cache_key = f"pm_{market_id}"
        if pm_cache_key not in price_cache:
            price_cache[pm_cache_key] = _get_pm_current_prices(market_id)
        current_yes_price, current_no_price = price_cache.get(pm_cache_key, (None, None))

        # 检查 PM 价格是否有效
        if current_yes_price is None or current_no_price is None:
            logger.warning(f"Skipping position {signal_id}: PM price unavailable "
                          f"(yes={current_yes_price}, no={current_no_price})")
            return None

        # 检查现货价格是否有效
        if current_spot is None:
            logger.warning(f"Skipping position {signal_id}: Spot price unavailable")
            return None

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

    # Handle Query objects when called directly (not via FastAPI)
    if status and isinstance(status, str):
        status_upper = status.strip().upper()
        if status_upper in ('OPEN', 'CLOSE'):
            conditions.append("UPPER(status) = ?")
            params.append(status_upper)

    if start_time and isinstance(start_time, str):
        conditions.append("entry_timestamp >= ?")
        params.append(start_time)

    if end_time and isinstance(end_time, str):
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
    current_spot: Optional[float] = None
    try:
        spot_value = DeribitAPI.get_spot_price("btc_usd")
        current_spot = _safe_float(spot_value, default=None)
        if current_spot is None:
            logger.warning("Spot price returned invalid value")
    except Exception as e:
        logger.warning(f"Failed to get spot price: {e}")

    # 价格缓存
    price_cache: dict = {}

    # 计算每个 position 的 PnL
    position_details: list[PnlPositionDetail] = []
    skipped_count = 0
    for row in rows:
        try:
            detail = _calculate_position_pnl(row, current_spot, price_cache)
            if detail is None:
                # 价格获取失败，跳过此 position
                skipped_count += 1
                continue
            position_details.append(detail)
        except Exception as e:
            logger.error(f"Failed to calculate PnL for {row.get('trade_id')}: {e}", exc_info=True)
            continue

    if skipped_count > 0:
        logger.info(f"Skipped {skipped_count} positions due to unavailable prices")

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


# ==================== 发送 PnL CSV 端点 ====================

class SendPnlResponse(BaseModel):
    """发送 PnL CSV 响应"""
    success: bool
    message: str
    file_path: Optional[str] = None


@pnl_router.post("/api/pnl/send", response_model=SendPnlResponse)
async def send_pnl_csv():
    """
    立即生成并发送 PnL CSV 到 Telegram。

    Returns:
        发送结果
    """
    import csv
    from datetime import datetime, timezone
    from pathlib import Path

    from ..core.config import load_all_configs
    from ..telegram.TG_bot import TG_bot

    try:
        # 获取当前 PnL 数据
        pnl_response = get_pnl_summary()

        if not pnl_response.positions:
            return SendPnlResponse(
                success=False,
                message="没有可用的 position 数据"
            )

        # 生成 CSV 文件
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        output_dir = Path("./data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"pnl_{date_str}_{time_str}.csv"

        # CSV 列名
        csv_columns = [
            "signal_id", "timestamp", "market_title",
            "funding_usd", "cost_basis_usd", "total_unrealized_pnl_usd", "im_value_usd",
            "shadow_pnl_usd", "real_pnl_usd",
            "pm_pnl_usd", "dr_pnl_usd", "fee_dr_usd", "currency_pnl_usd",
            "diff_usd", "residual_error_usd",
            "ev_usd", "total_pnl_usd",
            "leg1_instrument", "leg1_qty", "leg1_entry_price", "leg1_current_price", "leg1_pnl",
            "leg2_instrument", "leg2_qty", "leg2_entry_price", "leg2_current_price", "leg2_pnl",
        ]

        # 写入 CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()

            for position in pnl_response.positions:
                row = {
                    "signal_id": position.signal_id,
                    "timestamp": position.timestamp,
                    "market_title": position.market_title,
                    "funding_usd": position.funding_usd,
                    "cost_basis_usd": position.cost_basis_usd,
                    "total_unrealized_pnl_usd": position.total_unrealized_pnl_usd,
                    "im_value_usd": position.im_value_usd,
                    "shadow_pnl_usd": position.shadow_view.pnl_usd,
                    "real_pnl_usd": position.real_view.pnl_usd,
                    "pm_pnl_usd": position.pm_pnl_usd,
                    "dr_pnl_usd": position.dr_pnl_usd,
                    "fee_dr_usd": position.fee_dr_usd,
                    "currency_pnl_usd": position.currency_pnl_usd,
                    "diff_usd": position.diff_usd,
                    "residual_error_usd": position.residual_error_usd,
                    "ev_usd": position.ev_usd,
                    "total_pnl_usd": position.total_pnl_usd,
                }

                # 展开 legs
                legs = position.shadow_view.legs
                if len(legs) >= 1:
                    row["leg1_instrument"] = legs[0].instrument
                    row["leg1_qty"] = legs[0].qty
                    row["leg1_entry_price"] = legs[0].entry_price
                    row["leg1_current_price"] = legs[0].current_price
                    row["leg1_pnl"] = legs[0].pnl
                if len(legs) >= 2:
                    row["leg2_instrument"] = legs[1].instrument
                    row["leg2_qty"] = legs[1].qty
                    row["leg2_entry_price"] = legs[1].entry_price
                    row["leg2_current_price"] = legs[1].current_price
                    row["leg2_pnl"] = legs[1].pnl

                writer.writerow(row)

        # 初始化 Telegram bot 并发送
        env, _, _ = load_all_configs()
        bot = TG_bot(
            name="pnl_send",
            token=env.TELEGRAM_BOT_TOKEN_TRADING,
            chat_id=env.TELEGRAM_CHAT_ID
        )

        # 生成摘要
        caption = f"📊 PnL Report: {date_str} {time_str}\n"
        caption += f"Positions: {pnl_response.total_positions}\n"
        caption += f"Shadow PnL: ${pnl_response.shadow_view.pnl_usd:.2f}\n"
        caption += f"Real PnL: ${pnl_response.real_view.pnl_usd:.2f}\n"
        caption += f"Cost Basis: ${pnl_response.total_cost_basis_usd:.2f}\n"
        caption += f"Total EV: ${pnl_response.total_ev_usd:.2f}"

        success, msg_id = await bot.send_document(
            file_path=str(output_path),
            caption=caption
        )

        if success:
            logger.info(f"Sent PnL CSV via API: {output_path}, message_id: {msg_id}")
            return SendPnlResponse(
                success=True,
                message=f"已发送 PnL CSV 到 Telegram (message_id: {msg_id})",
                file_path=str(output_path)
            )
        else:
            logger.error(f"Failed to send PnL CSV: {output_path}")
            return SendPnlResponse(
                success=False,
                message="发送 Telegram 失败",
                file_path=str(output_path)
            )

    except Exception as e:
        logger.error(f"Error sending PnL CSV: {e}", exc_info=True)
        return SendPnlResponse(
            success=False,
            message=f"发送失败: {str(e)}"
        )
