from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from core.deribit_client import DeribitUserCfg
from core.polymarket_client import get_polymarket_slippage
from strategy.early_exit import make_exit_decision
from strategy.models import ExitDecision, OptionPosition, Position
from strategy.strategy import (
    BlackScholesPricer,
    CalculationInput,
    PMEParams,
    calculate_pme_margin,
    main_calculation,
)
from utils.market_context import DeribitMarketContext, PolymarketState


@dataclass
class InvestmentResult:
    """单次投资测算的结果以及生成 CSV 所需字段。"""

    investment: float

    ev_yes: float
    ev_no: float

    total_costs_yes: float
    total_costs_no: float

    im_usd: float
    im_btc: float
    contracts: float

    pm_yes_slippage: float
    pm_no_slippage: float
    slippage_rate_used: float

    calc_input: CalculationInput

    def to_csv_row(
        self,
        timestamp: str,
        deribit_ctx: DeribitMarketContext,
        poly_ctx: PolymarketState,
    ) -> Dict[str, Any]:
        """构造与原逻辑兼容的一行 CSV 数据。"""
        return {
            # === 基础信息 ===
            "timestamp": timestamp,
            "market_title": deribit_ctx.title,
            "asset": deribit_ctx.asset,
            "investment": self.investment,
            # === 市场价格相关 ===
            "spot": deribit_ctx.spot,
            "poly_yes_price": poly_ctx.yes_price,
            "poly_no_price": poly_ctx.no_price,
            "deribit_prob": deribit_ctx.deribit_prob,
            # === 合约名 ===
            "k1_instrument": deribit_ctx.inst_k1,
            "k2_instrument": deribit_ctx.inst_k2,
            # === Deribit 参数 ===
            "K1": deribit_ctx.k1_strike,
            "K2": deribit_ctx.k2_strike,
            "K_poly": deribit_ctx.K_poly,
            "T": deribit_ctx.T,
            "days_to_expiry": self.calc_input.days_to_expiry,
            "sigma": deribit_ctx.mark_iv / 100.0,
            "r": deribit_ctx.r,
            "k1_bid_btc": deribit_ctx.k1_bid_btc,
            "k1_ask_btc": deribit_ctx.k1_ask_btc,
            "k2_bid_btc": deribit_ctx.k2_bid_btc,
            "k2_ask_btc": deribit_ctx.k2_ask_btc,
            "k1_mid_usd": deribit_ctx.k1_mid_usd,
            "k2_mid_usd": deribit_ctx.k2_mid_usd,
            # === Polymarket & Slippage ===
            "pm_yes_slippage": self.pm_yes_slippage,
            "pm_no_slippage": self.pm_no_slippage,
            "slippage_rate_used": self.slippage_rate_used,
            # === 成本 / 保证金 ===
            "total_costs_yes": self.total_costs_yes,
            "total_costs_no": self.total_costs_no,
            "IM_usd": self.im_usd,
            "IM_btc": self.im_btc,
            "contracts": self.contracts,
            # === 策略计算相关参数 ===
            "Price_No_entry": self.calc_input.Price_No_entry,
            "Call_K1_Bid": self.calc_input.Call_K1_Bid,
            "Call_K1_Ask": self.calc_input.Call_K1_Ask,
            "Call_K2_Bid": self.calc_input.Call_K2_Bid,
            "Call_K2_Ask": self.calc_input.Call_K2_Ask,
            # === 最后两列必须是 EV ===
            "ev_yes": self.ev_yes,
            "ev_no": self.ev_no,
        }


async def evaluate_investment(
    inv_base_usd: float,
    deribit_ctx: DeribitMarketContext,
    poly_ctx: PolymarketState,
    deribit_user_cfg: DeribitUserCfg,
) -> InvestmentResult:
    """对单笔投资进行完整的 Slippage、保证金、EV 等测算。"""

    # === 1. Polymarket slippage 估计 ===
    try:
        pm_yes_open = await get_polymarket_slippage(
            poly_ctx.yes_token_id,
            inv_base_usd,
            side="buy",
            amount_type="usd",
        )
        pm_yes_avg_open = float(pm_yes_open["avg_price"])
        pm_yes_shares_open = float(pm_yes_open["shares_executed"])
        pm_yes_slip_open = float(pm_yes_open["slippage_pct"]) / 100.0

        pm_yes_close = await get_polymarket_slippage(
            poly_ctx.yes_token_id,
            pm_yes_shares_open,
            side="sell",
            amount_type="shares",
        )
        pm_yes_avg_close = float(pm_yes_close["avg_price"])
        pm_yes_slip_close = float(pm_yes_close["slippage_pct"]) / 100.0

        pm_no_open = await get_polymarket_slippage(
            poly_ctx.no_token_id,
            inv_base_usd,
            side="buy",
            amount_type="usd",
        )
        pm_no_avg_open = float(pm_no_open["avg_price"])
        pm_no_shares_open = float(pm_no_open["shares_executed"])
        pm_no_slip_open = float(pm_no_open["slippage_pct"]) / 100.0

        pm_no_close = await get_polymarket_slippage(
            poly_ctx.no_token_id,
            pm_no_shares_open,
            side="sell",
            amount_type="shares",
        )
        pm_no_avg_close = float(pm_no_close["avg_price"])
        pm_no_slip_close = float(pm_no_close["slippage_pct"]) / 100.0

    except Exception as exc:
        # 交由上层统一处理
        raise RuntimeError("Polymarket slippage calculation failed") from exc

    slippage_rate_used = max(pm_yes_slip_open, pm_no_slip_open)

    # === 2. 头寸与合约张数（基于 Delta 对冲 PM BTC 敞口）===
    pricer = BlackScholesPricer()

    # 1) PM 投注金额 -> BTC 名义敞口
    #    PM_BTC_exposure = Inv_Base / S
    if deribit_ctx.spot > 0:
        pm_btc_exposure = inv_base_usd / deribit_ctx.spot
    else:
        pm_btc_exposure = 0.0

    # 2) 用 BS 模型算两个 Call 的 Delta
    delta_k1 = pricer.calculate_greeks(
        S=deribit_ctx.spot,
        K=deribit_ctx.k1_strike,
        T=deribit_ctx.T,
        r=deribit_ctx.r,
        sigma=deribit_ctx.mark_iv / 100.0,
        option_type="call",
    ).delta

    delta_k2 = pricer.calculate_greeks(
        S=deribit_ctx.spot,
        K=deribit_ctx.k2_strike,
        T=deribit_ctx.T,
        r=deribit_ctx.r,
        sigma=deribit_ctx.mark_iv / 100.0,
        option_type="call",
    ).delta

    # 价差净 Delta：Δ_spread = Δ(K1) - Δ(K2)
    spread_delta = abs(delta_k1 - delta_k2)

    # 3) 合约数量：
    #    Contracts = PM_BTC_exposure / |Δ_spread|
    amount_contracts = pm_btc_exposure / spread_delta if spread_delta > 0 else 0.0

    # === 3. Deribit 初始保证金（使用 PME 风险矩阵计算）===
    pme_positions = [
        OptionPosition(
            strike=deribit_ctx.k1_strike,
            direction="long",
            contracts=amount_contracts,
            current_price=deribit_ctx.k1_mid_usd,
            implied_vol=deribit_ctx.mark_iv / 100.0,
            option_type="call",
        ),
        OptionPosition(
            strike=deribit_ctx.k2_strike,
            direction="short",
            contracts=amount_contracts,
            current_price=deribit_ctx.k2_mid_usd,
            implied_vol=deribit_ctx.mark_iv / 100.0,
            option_type="call",
        ),
    ]

    pme_margin_result = calculate_pme_margin(
        positions=pme_positions,
        current_index_price=deribit_ctx.spot,
        days_to_expiry=deribit_ctx.T * 365.0,
        pme_params=PMEParams(),
    )

    im_value_usd = float(pme_margin_result["c_dr_usd"])
    im_value_btc = im_value_usd / deribit_ctx.spot if deribit_ctx.spot else 0.0

    # === 4. 调用统一的收益 / 风险计算引擎 ===
    calc_input = CalculationInput(
        S=deribit_ctx.spot,
        K=deribit_ctx.k1_strike,
        T=deribit_ctx.T,
        r=deribit_ctx.r,
        sigma=deribit_ctx.mark_iv / 100.0,
        K1=deribit_ctx.k1_strike,
        K_poly=deribit_ctx.K_poly,
        K2=deribit_ctx.k2_strike,
        Inv_Base=inv_base_usd,
        Call_K1_Bid=deribit_ctx.k1_bid_usd,
        Call_K2_Ask=deribit_ctx.k2_ask_usd,
        Price_No_entry=poly_ctx.no_price,
        Call_K1_Ask=deribit_ctx.k1_ask_usd,
        Call_K2_Bid=deribit_ctx.k2_bid_usd,
        Price_Option1=deribit_ctx.k1_mid_usd,
        Price_Option2=deribit_ctx.k2_mid_usd,
        BTC_Price=deribit_ctx.spot,
        Slippage_Rate=slippage_rate_used,
        Margin_Requirement=im_value_usd,
        Total_Investment=inv_base_usd,
        pme_params=PMEParams(),
        contracts=float(amount_contracts),
        days_to_expiry=float(deribit_ctx.T * 365.0),
    )

    result = main_calculation(
        calc_input,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=poly_ctx.yes_price,
        calculate_greeks=False,
        bs_edge_threshold=0.03,
    )

    # === 1. EV ===
    ev_yes = float(result.expected_pnl_strategy1.Total_Expected)
    ev_no = float(result.expected_pnl_strategy2.Total_Expected)

    # === 2. 拆解成本结构 ===
    # 这三部分结构在 strategy.calculate_costs 里定义好：
    # Total_Cost = Open_Cost + Holding_Cost + Close_Cost
    open_cost = float(result.costs.Open_Cost)
    holding_cost = float(result.costs.Holding_Cost)
    close_cost_base = float(result.costs.Close_Cost)

    # strategy.calculate_costs 里：
    #   pm_slippage = Inv_Base * Slippage_Rate
    #   close_cost = pm_slippage + settlement_fee + blockchain_close
    # 这里用当时传给 main_calculation 的 slippage_rate_used 还原：
    pm_slippage_base = inv_base_usd * slippage_rate_used
    blockchain_close = 0.025
    # 防止浮点误差搞出负数，做个 max(...)
    settlement_fee = max(close_cost_base - pm_slippage_base - blockchain_close, 0.0)

    # === 3. 分别用 YES / NO 自己的 PM 滑点重建 close 成本 ===
    # 目前我们沿用之前的口径：只用 open 时刻的滑点率来代表 PM 滑点，
    # 如果以后要把 close 的滑点也加进去，可以在这里调整权重。
    close_cost_yes = inv_base_usd * pm_yes_slip_open + settlement_fee + blockchain_close
    close_cost_no = inv_base_usd * pm_no_slip_open + settlement_fee + blockchain_close

    total_costs_yes = open_cost + holding_cost + close_cost_yes
    total_costs_no = open_cost + holding_cost + close_cost_no

    return InvestmentResult(
        investment=inv_base_usd,
        ev_yes=ev_yes,
        ev_no=ev_no,
        total_costs_yes=total_costs_yes,
        total_costs_no=total_costs_no,
        im_usd=im_value_usd,
        im_btc=im_value_btc,
        contracts=float(amount_contracts),
        pm_yes_slippage=pm_yes_slip_open,
        pm_no_slippage=pm_no_slip_open,
        slippage_rate_used=slippage_rate_used,
        calc_input=calc_input,
    )


async def evaluate_early_exit_for_position(
    *,
    position: Position,
    base_result: InvestmentResult,
    settlement_price: float,
    pm_exit_price: float,
    available_liquidity_tokens: float,
    early_exit_cfg: Dict[str, Any],
) -> ExitDecision:
    """
    利用 evaluate_investment 返回的 calc_input，
    再结合真实持仓信息 Position 和当前 PM 价格，给出提前平仓决策。

    注意：
    - position 需要由你的“真实下单记录”来构造（而不是 InvestmentResult）
    - settlement_price：DR 的真实结算价（08:00 结算后）
    - pm_exit_price：当前 PM 上你打算平仓的价格（可以用最佳买价 / 中间价）
    """
    if not hasattr(base_result, "calc_input") or base_result.calc_input is None:
        raise ValueError("InvestmentResult 缺少 calc_input，无法做提前平仓分析")

    calc_input = base_result.calc_input

    decision = make_exit_decision(
        position=position,
        calc_input=calc_input,
        settlement_price=settlement_price,
        pm_exit_price=pm_exit_price,
        available_liquidity_tokens=available_liquidity_tokens,
        early_exit_cfg=early_exit_cfg,
    )
    return decision