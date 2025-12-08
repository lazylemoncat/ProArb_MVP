def _has_open_position_for_market(rows: list[dict], market_id: str) -> bool:
    """检查某市场是否已有未平仓头寸，落实“同一市场不加仓”规则。"""
    market_id = str(market_id)
    for row in rows:
        if (
            str(row.get("status") or "").upper() == "OPEN"
            and str(row.get("market_id") or "") == market_id
        ):
            return True
    return False

def check_required_config():
    if realized_pnl <= -100 and not risk_review_triggered:
        risk_review_triggered = True
        console.print(
            "⚠️ [red]累计亏损已超过 100u，请立即人工复盘（不自动停止）。[/red]"
        )
    if abs(inv_base_usd - RULE_REQUIRED_INVESTMENT) > 1e-6:
        console.print(
            f"⏸️ [yellow]跳过非规则手数 {inv_base_usd:.0f}（仅允许运行 {RULE_REQUIRED_INVESTMENT:.0f}u）[/yellow]"
        )
    if daily_trades >= config.thresholds.daily_trades:
        console.print(f"⛔ [red]已达到当日 {config.thresholds.daily_trades} 笔交易上限，停止开仓。[/red]")
        continue
    if open_positions_count >= 1:
        console.print("⛔ [red]持仓数已达上限 1，暂停加仓。[/red]")
        continue
    if _has_open_position_for_market(positions_rows, market_id):
        console.print(
            f"⏸️ [yellow]{market_id} 已有持仓，规则禁止重复开仓，等待平仓后再试。[/yellow]"
        )
        continue