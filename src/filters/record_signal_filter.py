"""
发送 alert 信号和记入数据库的条件:

    1. 时间维度：
    - 距离上次记录 ≥ 5分钟
    2. 正净 ev
    - net_ev > 0

    以下(满足任一即可)

    1. EV 变化维度(需同时满足):
        - 相对变化：|新 ROI - 旧 ROI| ≥ 3%
        - 绝对变化：|新净 EV - 旧净 EV| ≥ 投资额 x 1.5%

    2. 状态切换维度：
        - EV 从负转正:立即记录
        - EV 从正转负:立即记录（风险信号）
        - 策略切换(策略1 ↔ 策略2):立即记录

    3. 市场关键变化(突破阈值立即记录):
        - PM 价格变化 ≥ 2%
        - Deribit 期权价格变化 ≥ 3%
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple


@dataclass
class SignalSnapshot:
    recorded_at: datetime
    net_ev: float
    roi_pct: float
    pm_price: float
    deribit_price: float
    strategy: int

@dataclass
class Record_signal_filter:
    time_window_seconds: int # 距离上次记录时间间隔
    roi_relative_pct_change: float # ROI 相对变化百分比
    net_ev_absolute_pct_change: float # 净 EV 绝对变化
    pm_price_pct_change: float # PM 价格变化百分比
    deribit_price_pct_change: float # Deribit 期权价格变化百分比

def check_time_condition(previous_snapshot: SignalSnapshot, record_signal_filter: Record_signal_filter) -> Tuple[bool, str]:
    """
    检查时间间隔是否大于 time_window_seconds
    """
    details = ""
    time_window_seconds = record_signal_filter.time_window_seconds

    now_time = datetime.now(timezone.utc)

    time_gap = (now_time - previous_snapshot.recorded_at).total_seconds()
    time_condition = time_gap >= time_window_seconds
    if not time_condition:
        details += f"时间间隔 {time_gap} 不大于等于要求的 {time_window_seconds} 秒 \n"
    else:
        details += f"时间间隔 {time_gap} 大于等于要求的 {time_window_seconds} 秒 \n"
    return time_condition, details

def check_ev_change_condition(
        now_snapshot: SignalSnapshot,
        previous_snapshot: SignalSnapshot,
        investment_usd: float, 
        record_signal_filter: Record_signal_filter
    ):
    """
    检查 EV 变化维度是否同时满足:
    - 相对变化：|新ROI - 旧ROI| ≥ 3%
    - 绝对变化：|新净EV - 旧净EV| ≥ 投资额 × 1.5%
    """
    details = ""
    roi_relative_pct_change = record_signal_filter.roi_relative_pct_change
    net_ev_absolute_pct_change = record_signal_filter.net_ev_absolute_pct_change

    now_roi_relative_change = abs(now_snapshot.roi_pct - previous_snapshot.roi_pct)
    now_net_ev_absolute_change = abs(now_snapshot.net_ev - previous_snapshot.net_ev)
    ev_change_condition = (
        now_roi_relative_change >= roi_relative_pct_change
        and now_net_ev_absolute_change >= investment_usd * net_ev_absolute_pct_change 
    )

    if not ev_change_condition:
        details += (
            "ROI 相对变化或 net ev 变化不满足条件\n"
            f"ROI 相对变化: {now_roi_relative_change}, 要求: {roi_relative_pct_change}"
            f"net ev 变化: {now_net_ev_absolute_change}, 要求: {net_ev_absolute_pct_change}"
        )
    else:
        details += (
            "ROI 相对变化或 net ev 变化满足条件\n"
            f"ROI 相对变化: {now_roi_relative_change}, 要求: {roi_relative_pct_change}"
            f"net ev 变化: {now_net_ev_absolute_change}, 要求: {net_ev_absolute_pct_change}"
        )
    
    return ev_change_condition, details

def check_sign_change_condition(now_snapshot: SignalSnapshot, previous_snapshot: SignalSnapshot, ):
    """
    检查状态切换维度：
    - EV从负转正: 立即记录
    - EV从正转负: 立即记录（风险信号）
    - 策略切换(策略1 ↔ 策略2): 立即记录
    """
    details = ""

    # 是否 EV从负转正
    is_ev_neg_to_pos = previous_snapshot.net_ev < 0 <= now_snapshot.net_ev
    if is_ev_neg_to_pos:
        details += f"EV从负转正: 立即记录"
    
    is_ev_pos_to_neg = previous_snapshot.net_ev > 0 >= now_snapshot.net_ev
    if is_ev_pos_to_neg:
        details += f"EV从正转负: 立即记录"
    
    is_strategy_change = now_snapshot.strategy != previous_snapshot.strategy
    if is_strategy_change:
        details += f"策略切换(策略{previous_snapshot.strategy} -> 策略{now_snapshot.strategy}): 立即记录"
    
    return bool(details), details

def check_market_change_condition(
        now_snapshot: SignalSnapshot, 
        previous_snapshot: SignalSnapshot, 
        record_signal_filter: Record_signal_filter
    ):
    """
    检查市场关键变化(突破阈值立即记录):
    - PM价格变化 ≥ 2%
    - Deribit期权价格变化 ≥ 3%
    """
    details = ""
    pm_price_pct_change = record_signal_filter.pm_price_pct_change
    deribit_price_pct_change = record_signal_filter.deribit_price_pct_change

    pm_base = previous_snapshot.pm_price if previous_snapshot.pm_price != 0 else 1e-8
    deribit_base = previous_snapshot.deribit_price if previous_snapshot.deribit_price != 0 else 1e-8

    now_pm_price_change = abs(now_snapshot.pm_price - previous_snapshot.pm_price)
    now_deribit_price_change = abs(now_snapshot.deribit_price - previous_snapshot.deribit_price)
    now_pm_price_pct_change = (now_pm_price_change / pm_base) * 100
    now_deribit_price_pct_change = (now_deribit_price_change / deribit_base) * 100

    market_change_condition = (
        now_pm_price_pct_change >= pm_price_pct_change
        or now_deribit_price_pct_change >= deribit_price_pct_change
    )

    if not market_change_condition:
        details += (
            f"PM 价格变化 {now_pm_price_pct_change} 不大于等于 {pm_price_pct_change}"
            f"Deribit 期权价格变化 {now_deribit_price_pct_change} 不大于等于 {deribit_price_pct_change}"
        )
    
    return market_change_condition, details