from __future__ import annotations

from datetime import datetime, timezone
from typing import Union

from .models import OpportunityMessage, TradeMessage, ErrorMessage, RecoveryMessage, TelegramMessage


def _fmt_money(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}"


def _fmt_ts_iso_to_utc(ts: str) -> str:
    # Accept "2025-01-24T15:32:18Z" or "+00:00"
    try:
        ts2 = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts2)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts


def _strategy_desc(strategy: int) -> str:
    return "买YES+卖牛差" if strategy == 1 else "买NO+买牛差"


def format_message(msg: TelegramMessage) -> str:
    if isinstance(msg, OpportunityMessage):
        d = msg.data
        return (
            f"🔴 [套利机会] {d.market_title} | EV: +${_fmt_money(d.net_ev)}\n"
            f"📊 策略{d.strategy}: {_strategy_desc(d.strategy)} | 概率差: +{d.prob_diff:.1f}%\n"
            f"💰 PM ${d.pm_price:.4f} | Deribit {d.deribit_price:.4f}\n"
            f"💵 建议投资: ${_fmt_money(d.investment, 0)}\n"
            f"⚠️ 数据延迟: {d.data_lag_seconds:.0f}s\n"
            f"⏰ {_fmt_ts_iso_to_utc(d.timestamp)}"
        )

    if isinstance(msg, ErrorMessage):
        d = msg.data
        return (
            "❌ 系统错误\n"
            f"组件: {d.component}\n"
            f"错误: {d.error_msg}\n"
            f"时间: {_fmt_ts_iso_to_utc(d.timestamp)}"
        )

    if isinstance(msg, RecoveryMessage):
        d = msg.data
        return (
            "✅ 系统恢复\n"
            f"组件: {d.component}\n"
            f"停机时间: {d.downtime_minutes:.0f}分钟\n"
            f"时间: {_fmt_ts_iso_to_utc(d.timestamp)}"
        )

    if isinstance(msg, TradeMessage):
        d = msg.data
        return (
            "💰 交易已执行\n"
            f"类型: {d.action}\n"
            f"策略: {d.strategy}\n"
            f"市场: {d.market_title}\n"
            f"PM: {d.pm_side} {d.pm_token} @ ${d.pm_price:.4f} (${_fmt_money(d.pm_amount_usd, 0)})\n"
            f"Deribit: {d.deribit_action} {d.deribit_k1}-{d.deribit_k2} ({d.deribit_contracts:.6f}份)\n"
            f"手续费: ${_fmt_money(d.fees_total)} | 滑点: ${_fmt_money(d.slippage_usd)}\n"
            f"开仓成本: ${_fmt_money(d.open_cost)} | 保证金: ${_fmt_money(d.margin_usd)}\n"
            f"预期净收益: ${_fmt_money(d.net_ev)}\n"
            f"备注: {d.note}\n" if d.note else ""
            f"⏰ {_fmt_ts_iso_to_utc(d.timestamp)}"
        )

    # Should be unreachable due to discriminator
    return str(msg)
