from .record_signal_filter import (
    SignalSnapshot, 
    Record_signal_filter, 
    check_time_condition, 
    check_ev_change_condition, 
    check_sign_change_condition, 
    check_market_change_condition
)

def should_record_signal(
    now_snapshot: SignalSnapshot, 
    previous_snapshot: SignalSnapshot,
    investment_usd: float,
    record_signal_filter: Record_signal_filter
):
    """
    发送 alert 信号和记入数据库的条件:

        1. 时间维度
        2. 正净 ev

        以下(满足任一即可)

        1. EV 变化维度(需同时满足)
        2. 状态切换维度
        3. 市场关键变化(突破阈值立即记录)
    """
    details: str = ""
    
    if now_snapshot.net_ev <= 0:
        return False, "net_ev <= 0"

    time_condition, temp_details = check_time_condition(previous_snapshot, record_signal_filter)
    details += temp_details

    ev_change_condition, temp_details = check_ev_change_condition(
        now_snapshot, 
        previous_snapshot, 
        investment_usd,
        record_signal_filter
    )
    details += temp_details

    sign_change_condition, temp_details = check_sign_change_condition(now_snapshot, previous_snapshot)
    details += temp_details

    market_change_condition = check_market_change_condition(now_snapshot, previous_snapshot, record_signal_filter)
    details += temp_details

    return time_condition and any(
        [
            ev_change_condition,
            sign_change_condition,
            market_change_condition,
        ]
    ), details