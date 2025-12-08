"""
    若 pm 交易资金大于规定 200 u, 跳过交易
    若当日已交易达到规定 1 笔上限, 跳过交易
    若总持仓数已达到规定 3 个, 跳过交易
    若该 pm 市场已有持仓, 规则禁止重复开仓, 跳过交易
    若 pm 订单簿深度不足以完全吃下给定 amount, 跳过交易
    若合约数量不能达到 deribit 的最小 0.1 合约, 跳过交易
    若合约数量的调整幅度大于 30%, 跳过交易
    若合约数量小于配置文件的规定数量 0.1, 跳过交易
    PM价格 < 0.01 拒绝
    PM价格 > 0.99 拒绝
    净利润小于规定 0.0 时(只接受正EV), 跳过交易
    ROI 低于规定 1.0 时, 跳过交易
    概率差小于规定 0.01 时, 跳过交易
"""

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
    if abs(inv_base_usd - RULE_REQUIRED_INVESTMENT) > 1e-6:
        console.print(
            f"⏸️ [yellow]跳过非规则手数 {inv_base_usd:.0f}(仅允许运行 {RULE_REQUIRED_INVESTMENT:.0f}u)[/yellow]"
        )
    if daily_trades >= config.thresholds.daily_trades:
        console.print(f"⛔ [red]已达到当日 {config.thresholds.daily_trades} 笔交易上限，停止开仓。[/red]")
        continue
    if open_positions_count >= 3:
        console.print("⛔ [red]持仓数已达上限 1，暂停加仓。[/red]")
        continue
    if _has_open_position_for_market(positions_rows, market_id):
        console.print(
            f"⏸️ [yellow]{market_id} 已有持仓，规则禁止重复开仓，等待平仓后再试。[/yellow]"
        )
        continue