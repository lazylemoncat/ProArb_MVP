from .trade_filter import (
    Trade_filter,
    Trade_filter_input,
    check_adjust_contract_amount,
    check_contract_amount,
    check_daily_trades_condition,
    check_inv_condition,
    check_net_ev,
    check_open_positions_counts,
    check_pm_price,
    check_prob_edge_pct,
    check_repeat_open_position,
    check_roi_pct,
)

from .record_signal_filter import (
    Record_signal_filter,
    SignalSnapshot,
    check_ev_change_condition,
    check_market_change_condition,
    check_sign_change_condition,
    check_time_condition,
)


def check_should_record_signal(
    now_snapshot: SignalSnapshot, 
    previous_snapshot: SignalSnapshot | None,
    investment_usd: float,
    record_signal_filter: Record_signal_filter,
) -> tuple[bool, str, bool]:
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
    
    if previous_snapshot is None:
        time_condition = True
    else:
        time_condition, temp_details = check_time_condition(previous_snapshot, record_signal_filter)
        details += temp_details

    if now_snapshot.net_ev <= 0:
        return False, "net_ev <= 0", time_condition
    elif previous_snapshot is None:
        return True, "", True


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
    ), details, time_condition

def check_should_trade_signal(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: str = ""
    
    inv_condition, temp_details = check_inv_condition(trade_filter_input, trade_filter)
    details += temp_details

    daily_trades_condition, temp_details = check_daily_trades_condition(trade_filter_input, trade_filter)
    details += temp_details

    positions_counts_conditions, temp_details = check_open_positions_counts(trade_filter_input, trade_filter)
    details += temp_details

    repeat_open_condition, temp_details = check_repeat_open_position(
        trade_filter_input,
        trade_filter, 
    )
    details += temp_details

    contract_amount_condition, temp_details = check_contract_amount(trade_filter_input, trade_filter)
    details += temp_details

    adjust_contract_amount_condition, temp_details = check_adjust_contract_amount(
        trade_filter_input,
        trade_filter
    )
    details += temp_details

    pm_price_condition, temp_details = check_pm_price(trade_filter_input, trade_filter)
    details += temp_details

    net_ev_condition, temp_details = check_net_ev(trade_filter_input, trade_filter)
    details += temp_details

    roi_condition, temp_details = check_roi_pct(trade_filter_input, trade_filter)
    details += temp_details

    prob_edge_pct_condition, temp_details = check_prob_edge_pct(trade_filter_input, trade_filter)
    details += temp_details

    return all(
        [
            inv_condition,
            daily_trades_condition,
            positions_counts_conditions,
            repeat_open_condition,
            contract_amount_condition,
            adjust_contract_amount_condition,
            pm_price_condition,
            net_ev_condition,
            roi_condition,
            prob_edge_pct_condition
        ]
    ), details