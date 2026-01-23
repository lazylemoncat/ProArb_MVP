"""
    若 pm 交易资金大于规定 200 u, 跳过交易
    若当日已交易达到规定 1 笔上限, 跳过交易
    若总持仓数已达到规定 3 个, 跳过交易
    若该 pm 市场已有持仓, 规则禁止重复开仓, 跳过交易
    若 pm 订单簿深度不足以完全吃下给定 amount, 跳过交易 # Insufficient_liquidity
    若合约数量不能达到 deribit 的最小 0.1 合约, 跳过交易
    若合约数量的调整幅度大于 30%, 跳过交易
    若合约数量小于配置文件的规定数量 0.1, 跳过交易
    PM价格 < 0.01 拒绝
    PM价格 > 0.99 拒绝
    净利润小于规定 0.0 时(只接受正EV), 跳过交易
    ROI 低于规定 1.0 时, 跳过交易
    概率差小于规定 0.01 时, 跳过交易
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from ...utils.SqliteHandler import SqliteHandler
from ..save.save_position import SavePosition


@dataclass
class Trade_filter_input:
    inv_usd: float
    market_id: str
    contract_amount: float
    pm_price: float
    net_ev: float
    roi_pct: float
    prob_edge_pct: float

@dataclass
class Trade_filter:
    inv_usd_limit: float                # 交易资金上限
    daily_trade_limit: int              # 每日交易次数上限
    open_positions_limit: int           # 总共持仓上限
    allow_repeat_open_position: bool    # 允许对已有持仓进行交易
    min_contract_amount: int            # 最小交易合约数量
    contract_rounding_band: int         # 合约数调整范围系数；1 表示允许在目标合约数的 ±10% 内四舍五入到最接近的 0.1
    min_pm_price: float                 # 最小允许 pm 的价格
    max_pm_price: float                 # 最大允许 pm 的价格
    min_net_ev: float                   # 最小允许净利润
    min_roi_pct: float                  # 最小允许 roi
    min_prob_edge_pct: float            # 最小允许概率差

def _load_positions() -> list[dict]:
    """从 SQLite 加载所有持仓数据"""
    try:
        return SqliteHandler.query_table(class_obj=SavePosition)
    except Exception:
        return []

def _count_daily_trades(rows: list[dict], day: date) -> int:
    """统计指定日期内已执行的真实交易数量，用于每日最多 1 笔的仓位管理规则。"""
    count = 0
    for row in rows:
        ts = row.get("entry_timestamp") or ""
        try:
            # Handle both string and datetime types
            if isinstance(ts, datetime):
                ts_date = ts.date()
            else:
                ts_date = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except Exception:
            continue
        if ts_date == day and str(row.get("status") or "").upper() != "DRY_RUN":
            count += 1
    return count


def _count_open_positions(rows: list[dict]) -> int:
    """计算当前 SQLite 中仍为 OPEN 的记录数量，对应最大持仓数 3 的限制。"""
    return sum(1 for row in rows if str(row.get("status") or "").upper() == "OPEN")

def _has_open_position_for_market(rows: list[dict], market_id: str) -> bool:
    """检查某市场是否已有未平仓头寸，落实"同一市场不加仓"规则。"""
    market_id = str(market_id)
    for row in rows:
        if (
            str(row.get("status") or "").upper() == "OPEN"
            and str(row.get("market_id") or "") == market_id
        ):
            return True
    return False

def check_inv_condition(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    # 若 pm 交易资金大于规定数, 跳过交易
    details: str = ""

    if trade_filter_input.inv_usd > trade_filter.inv_usd_limit:
        details += f"资金{trade_filter_input.inv_usd} 超过限制: {trade_filter.inv_usd_limit}"
        return False, details
    return True, details

def check_daily_trades_condition(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    # 若当日已交易达到规定上限, 跳过交易
    details: str = ""

    positions_rows = _load_positions()
    today = datetime.now(timezone.utc).date()
    daily_trades = _count_daily_trades(positions_rows, today)
    if daily_trades >= trade_filter.daily_trade_limit:
        details += f"当日交易次数已达上限: {trade_filter.daily_trade_limit}"
        return False, details
    return True, details

def check_open_positions_counts(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    # 若总持仓数已达到规定数, 跳过交易
    details: str = ""

    positions_rows = _load_positions()
    count_open_positions = _count_open_positions(positions_rows)
    if count_open_positions >= trade_filter.open_positions_limit:
        details += f"目前持仓数量 {count_open_positions} 个, 达到规定 {trade_filter.open_positions_limit} 个上限"
        return False, details
    return True, details

def check_repeat_open_position(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter.allow_repeat_open_position:
        return True, details

    positions_rows = _load_positions()
    if _has_open_position_for_market(positions_rows, trade_filter_input.market_id):
        details += f"{trade_filter_input.market_id} 已有持仓且规则不允许重复开仓"
        return False, details
    return True, details

def check_contract_amount(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    # 若合约数量不能达到 deribit 的最小 0.1 合约, 跳过交易
    # 若合约数量小于配置文件的规定数量, 跳过交易
    details: str = ""

    if trade_filter_input.contract_amount < 0.1:
        details += f"合约数量 {trade_filter_input.contract_amount} 小于 deribit 要求的 0.1 合约"
        return False, details
    if trade_filter_input.contract_amount < trade_filter.min_contract_amount:
        details += f"合约数量 {trade_filter_input.contract_amount} 小于规定要求的 {trade_filter.min_contract_amount} 合约"
        return False, details
    return True, details

def check_adjust_contract_amount(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter.contract_rounding_band <= 0:
        return True, details
    raw_contract_amount = trade_filter_input.contract_amount
    rounded_contracts = round(trade_filter_input.contract_amount * 10) / 10.0
    rounding_tolerance = rounded_contracts * trade_filter.contract_rounding_band * 0.1
    lower_bound = rounded_contracts - rounding_tolerance
    upper_bound = rounded_contracts + rounding_tolerance

    if lower_bound <= raw_contract_amount <= upper_bound:
        raw_contract_amount = rounded_contracts
        trade_filter_input.contract_amount = raw_contract_amount
    else:
        details += f"合约数 {raw_contract_amount:.4f} 不在允许的 {rounded_contracts:.1f} ± {rounding_tolerance:.2f} 范围内"
        return False, details
    return True, details

def check_pm_price(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter_input.pm_price < trade_filter.min_pm_price:
        details += f"pm_price {trade_filter_input.pm_price} 小于规定要求的 {trade_filter.min_pm_price}"
        return False, details
    if trade_filter_input.pm_price > trade_filter.max_pm_price:
        details += f"pm_price {trade_filter_input.pm_price} 大于规定要求的 {trade_filter.max_pm_price}"
        return False, details
    return True, details

def check_net_ev(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter_input.net_ev <= trade_filter.min_net_ev:
        details += f"net_ev {trade_filter_input.net_ev} 小于等于规定的 {trade_filter.min_net_ev}"
        return False, details
    return True, details

def check_roi_pct(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter_input.roi_pct <= trade_filter.min_roi_pct:
        details += f"roi {trade_filter_input.roi_pct} 小于等于规定的 {trade_filter.min_roi_pct}"
        return False, details
    return True, details

def check_prob_edge_pct(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""

    if trade_filter_input.prob_edge_pct < trade_filter.min_prob_edge_pct:
        details += f"概率差 {trade_filter_input.prob_edge_pct} 小于规定的 {trade_filter.min_prob_edge_pct}"
        return False, details
    return True, details
