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
) -> tuple[bool, list[str], bool]:
    """
    发送 alert 信号和记入数据库的条件:

        1. 时间维度
        2. 正净 ev

        以下(满足任一即可)

        1. EV 变化维度(需同时满足)
        2. 状态切换维度
        3. 市场关键变化(突破阈值立即记录)
    """
    details: list[str] = []
    
    if previous_snapshot is None:
        return False, [], False
    
    time_condition, detail = check_time_condition(previous_snapshot, record_signal_filter)
    details.append(detail)

    if not time_condition:
        return False, details, time_condition

    if now_snapshot.net_ev <= 0:
        return False, ["net_ev <= 0"], time_condition


    ev_change_condition, detail = check_ev_change_condition(
        now_snapshot, 
        previous_snapshot, 
        investment_usd,
        record_signal_filter
    )
    details.append(detail)

    sign_change_condition, detail = check_sign_change_condition(now_snapshot, previous_snapshot)
    details.append(detail)

    market_change_condition, detail = check_market_change_condition(now_snapshot, previous_snapshot, record_signal_filter)
    details.append(detail)

    return time_condition and any(
        [
            ev_change_condition,
            sign_change_condition,
            market_change_condition,
        ]
    ), details, time_condition

def check_should_trade_signal(trade_filter_input: Trade_filter_input, trade_filter: Trade_filter):
    details: list[str] = []
    
    inv_condition, detail = check_inv_condition(trade_filter_input, trade_filter)
    details.append(detail)

    daily_trades_condition, detail = check_daily_trades_condition(trade_filter_input, trade_filter)
    details.append(detail)

    positions_counts_conditions, detail = check_open_positions_counts(trade_filter_input, trade_filter)
    details.append(detail)

    repeat_open_condition, detail = check_repeat_open_position(
        trade_filter_input,
        trade_filter, 
    )
    details.append(detail)

    contract_amount_condition, detail = check_contract_amount(trade_filter_input, trade_filter)
    details.append(detail)

    adjust_contract_amount_condition, detail = check_adjust_contract_amount(
        trade_filter_input,
        trade_filter
    )
    details += detail

    pm_price_condition, detail = check_pm_price(trade_filter_input, trade_filter)
    details.append(detail)

    net_ev_condition, detail = check_net_ev(trade_filter_input, trade_filter)
    details.append(detail)

    roi_condition, detail = check_roi_pct(trade_filter_input, trade_filter)
    details.append(detail)

    prob_edge_pct_condition, detail = check_prob_edge_pct(trade_filter_input, trade_filter)
    details.append(detail)

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