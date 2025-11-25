from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ..fetch_data.get_polymarket_slippage import get_polymarket_slippage
from .early_exit import make_exit_decision
from .models import ExitDecision, OptionPosition, Position
from .strategy import (
    BlackScholesPricer,
    CalculationInput,
    PMEParams,
    calculate_pme_margin,
    main_calculation,
)
from ..utils.market_context import DeribitMarketContext, PolymarketState


@dataclass
class StrategyCosts:
    """单个策略的完整成本明细"""
    # PM成本
    pm_open_cost: float
    pm_close_cost: float

    # Deribit成本
    deribit_open_fee: float
    deribit_settlement_fee: float

    # 区块链费用
    blockchain_open: float
    blockchain_close: float

    # 保证金和持仓成本
    im_usd: float
    im_btc: float
    margin_cost: float
    opportunity_cost: float
    holding_cost: float

    # 总成本
    open_cost: float
    close_cost: float
    total_cost: float


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
    im_usd_strategy1: float
    im_usd_strategy2: float
    im_btc_strategy1: float
    im_btc_strategy2: float
    contracts: float

    pm_yes_slippage: float
    pm_no_slippage: float
    slippage_rate_used: float

    open_cost_yes: float
    open_cost_no: float
    holding_cost_yes: float
    holding_cost_no: float
    close_cost_yes: float
    close_cost_no: float

    calc_input: CalculationInput

    # === 新增：两个策略的完整数据 ===
    net_ev_strategy1: float = 0.0
    net_ev_strategy2: float = 0.0
    gross_ev_strategy1: float = 0.0
    gross_ev_strategy2: float = 0.0
    contracts_strategy1: float = 0.0
    contracts_strategy2: float = 0.0
    total_cost_strategy1: float = 0.0
    total_cost_strategy2: float = 0.0

    # === 新增：两个策略的成本明细 ===
    open_cost_strategy1: float = 0.0
    open_cost_strategy2: float = 0.0
    holding_cost_strategy1: float = 0.0
    holding_cost_strategy2: float = 0.0
    close_cost_strategy1: float = 0.0
    close_cost_strategy2: float = 0.0

    # === 新增：PM市场价格详情（用于套利分析）===
    best_ask_strategy1: float = 0.0
    best_bid_strategy1: float = 0.0
    mid_price_strategy1: float = 0.0
    spread_strategy1: float = 0.0
    best_ask_strategy2: float = 0.0
    best_bid_strategy2: float = 0.0
    mid_price_strategy2: float = 0.0
    spread_strategy2: float = 0.0

    def to_csv_row(
        self,
        timestamp: str,
        deribit_ctx: DeribitMarketContext,
        poly_ctx: PolymarketState,
        strategy: int,
    ) -> Dict[str, Any]:
        """构造清理后的 CSV 数据（无冗余字段）。"""
        result = {
            # === 基础信息 ===
            "timestamp": timestamp,
            "market_title": deribit_ctx.title,
            "asset": deribit_ctx.asset,
            "investment": self.investment,
            "selected_strategy": strategy,  # 明确标识选择的策略
            # === 市场价格相关 ===
            "spot": deribit_ctx.spot,
            "poly_yes_price": poly_ctx.yes_price,
            "poly_no_price": poly_ctx.no_price,
            "deribit_prob": deribit_ctx.deribit_prob,
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
            # === 策略1完整数据 ===
            "net_ev_strategy1": self.net_ev_strategy1,
            "gross_ev_strategy1": self.gross_ev_strategy1,
            "total_cost_strategy1": self.total_cost_strategy1,
            "open_cost_strategy1": self.open_cost_strategy1,
            "holding_cost_strategy1": self.holding_cost_strategy1,
            "close_cost_strategy1": self.close_cost_strategy1,
            "contracts_strategy1": self.contracts_strategy1,
            "im_usd_strategy1": self.im_usd_strategy1,
            # === 策略2完整数据 ===
            "net_ev_strategy2": self.net_ev_strategy2,
            "gross_ev_strategy2": self.gross_ev_strategy2,
            "total_cost_strategy2": self.total_cost_strategy2,
            "open_cost_strategy2": self.open_cost_strategy2,
            "holding_cost_strategy2": self.holding_cost_strategy2,
            "close_cost_strategy2": self.close_cost_strategy2,
            "contracts_strategy2": self.contracts_strategy2,
            "im_usd_strategy2": self.im_usd_strategy2,
            # === PM市场价格详情（用于套利分析）===
            "best_ask_strategy1": self.best_ask_strategy1,
            "best_bid_strategy1": self.best_bid_strategy1,
            "mid_price_strategy1": self.mid_price_strategy1,
            "spread_strategy1": self.spread_strategy1,
            "best_ask_strategy2": self.best_ask_strategy2,
            "best_bid_strategy2": self.best_bid_strategy2,
            "mid_price_strategy2": self.mid_price_strategy2,
            "spread_strategy2": self.spread_strategy2,
            # === 执行参数 ===
            "slippage_rate_used": self.slippage_rate_used,
        }

        # DEBUG: Print the keys to see what we're returning
        # print(f"🔍 [DEBUG CSV] Keys: {list(result.keys())}")
        return result


def calculate_strategy_costs(
    strategy: int,
    inv_base_usd: float,
    contracts: float,
    pm_shares: float,
    pm_avg_open: float,
    pm_avg_close: float,
    best_ask: float,
    best_bid: float,
    deribit_costs: dict,
    deribit_ctx: DeribitMarketContext,
    blockchain_open_fee: float = 0.025,
    blockchain_close_fee: float = 0.025,
) -> StrategyCosts:
    """
    计算单个策略的完整成本

    Args:
        strategy: 策略编号（1或2）
        inv_base_usd: 基础投资金额
        contracts: 期权合约数量
        pm_shares: Polymarket份额
        pm_avg_open: PM开仓平均价格
        pm_avg_close: PM平仓平均价格
        best_ask: PM市场最优卖价（买入时的参考价）
        best_bid: PM市场最优买价（卖出时的参考价）
        deribit_costs: Deribit成本字典
        deribit_ctx: Deribit市场上下文
        blockchain_open_fee: 区块链开仓费用（默认0.025 USD）
        blockchain_close_fee: 区块链平仓费用（默认0.025 USD）

    Returns:
        StrategyCosts: 包含所有成本明细的对象
    """
    # 1. PM 开仓成本（滑点成本）
    # 使用 best_ask 作为参考：这是实际买入时能获得的最优价格
    # 滑点成本 = 份额数 * (实际平均成交价 - 最优卖价)
    pm_open_cost = pm_shares * (pm_avg_open - best_ask)
    if pm_open_cost < 0:
        pm_open_cost = 0.0  # 开仓成本不应为负（理论上不会出现）

    # 2. PM 平仓成本（滑点成本）
    # 使用 best_bid 作为参考：这是实际卖出时能获得的最优价格
    # 滑点成本 = 份额数 * (最优买价 - 实际平均成交价)
    pm_close_cost = pm_shares * (best_bid - pm_avg_close)
    if pm_close_cost < 0:
        pm_close_cost = 0.0  # 平仓成本不应为负（理论上不会出现）

    # 3. Deribit 开仓和平仓费用
    deribit_open_fee = deribit_costs["deribit_open_fee"]
    deribit_settlement_fee = deribit_costs["deribit_settlement_fee"]

    # 4. 开仓和平仓总成本
    open_cost = pm_open_cost + deribit_open_fee + blockchain_open_fee
    close_cost = pm_close_cost + deribit_settlement_fee + blockchain_close_fee

    # 5. 计算保证金
    # 根据策略构建期权头寸
    if strategy == 1:
        # 策略1：卖牛市价差（short K1, long K2）
        positions = [
            OptionPosition(
                strike=deribit_ctx.k1_strike,
                direction="short",
                contracts=contracts,
                current_price=deribit_ctx.k1_bid_usd,
                implied_vol=deribit_ctx.mark_iv / 100.0,
                option_type="call",
            ),
            OptionPosition(
                strike=deribit_ctx.k2_strike,
                direction="long",
                contracts=contracts,
                current_price=deribit_ctx.k2_ask_usd,
                implied_vol=deribit_ctx.mark_iv / 100.0,
                option_type="call",
            ),
        ]
    else:
        # 策略2：买牛市价差（long K1, short K2）
        positions = [
            OptionPosition(
                strike=deribit_ctx.k1_strike,
                direction="long",
                contracts=contracts,
                current_price=deribit_ctx.k1_ask_usd,
                implied_vol=deribit_ctx.mark_iv / 100.0,
                option_type="call",
            ),
            OptionPosition(
                strike=deribit_ctx.k2_strike,
                direction="short",
                contracts=contracts,
                current_price=deribit_ctx.k2_bid_usd,
                implied_vol=deribit_ctx.mark_iv / 100.0,
                option_type="call",
            ),
        ]

    pme_margin_result = calculate_pme_margin(
        positions=positions,
        current_index_price=deribit_ctx.spot,
        days_to_expiry=deribit_ctx.T * 365.0,
        pme_params=PMEParams(),
    )

    im_value_usd = float(pme_margin_result["c_dr_usd"])
    im_value_btc = im_value_usd / deribit_ctx.spot if deribit_ctx.spot > 0 else 0.0

    # 6. 持仓成本
    holding_days = deribit_ctx.T * 365.0
    r = deribit_ctx.r
    margin_cost = im_value_usd * r * (holding_days / 365.0)
    opportunity_cost = inv_base_usd * r * (holding_days / 365.0)
    holding_cost = margin_cost + opportunity_cost

    # 7. 汇总总成本
    total_cost = open_cost + holding_cost + close_cost

    return StrategyCosts(
        pm_open_cost=pm_open_cost,
        pm_close_cost=pm_close_cost,
        deribit_open_fee=deribit_open_fee,
        deribit_settlement_fee=deribit_settlement_fee,
        blockchain_open=blockchain_open_fee,
        blockchain_close=blockchain_close_fee,
        im_usd=im_value_usd,
        im_btc=im_value_btc,
        margin_cost=margin_cost,
        opportunity_cost=opportunity_cost,
        holding_cost=holding_cost,
        open_cost=open_cost,
        close_cost=close_cost,
        total_cost=total_cost,
    )


async def evaluate_investment(
    inv_base_usd: float,
    deribit_ctx: DeribitMarketContext,
    poly_ctx: PolymarketState,
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
        pm_yes_avg_open = float(pm_yes_open.avg_price)
        pm_yes_shares_open = float(pm_yes_open.shares)
        pm_yes_slip_open = float(pm_yes_open.slippage_pct) / 100.0

        pm_yes_close = await get_polymarket_slippage(
            poly_ctx.yes_token_id,
            pm_yes_shares_open,
            side="sell",
            amount_type="shares",
        )
        pm_yes_avg_close = float(pm_yes_close.avg_price)
        pm_yes_slip_close = float(pm_yes_close.slippage_pct) / 100.0

        pm_no_open = await get_polymarket_slippage(
            poly_ctx.no_token_id,
            inv_base_usd,
            side="buy",
            amount_type="usd",
        )
        pm_no_avg_open = float(pm_no_open.avg_price)
        pm_no_shares_open = float(pm_no_open.shares)
        pm_no_slip_open = float(pm_no_open.slippage_pct) / 100.0

        pm_no_close = await get_polymarket_slippage(
            poly_ctx.no_token_id,
            pm_no_shares_open,
            side="sell",
            amount_type="shares",
        )
        pm_no_avg_close = float(pm_no_close.avg_price)
        pm_no_slip_close = float(pm_no_close.slippage_pct) / 100.0

    except Exception as exc:
        # 保留底层错误信息，便于定位（例如流动性不足/盘口为空）
        raise RuntimeError("Polymarket slippage calculation failed: ", exc) from exc

    # === 2. 分别计算两个策略的合约数量 ===
    # 策略1：买YES + 卖牛看涨价差
    # 策略2：买NO + 买牛看涨价差

    # Deribit牛市价差分析
    spread_width = deribit_ctx.k2_strike - deribit_ctx.k1_strike

    if spread_width <= 0:
        raise ValueError(f"Invalid spread width: {spread_width}. K2 ({deribit_ctx.k2_strike}) must be > K1 ({deribit_ctx.k1_strike})")

    # 策略1：基于YES份数计算合约数（买YES，卖牛差）
    contracts_strategy1 = pm_yes_shares_open / spread_width

    # 策略2：基于NO份数计算合约数（买NO，买牛差）
    contracts_strategy2 = pm_no_shares_open / spread_width

    # === 3. 分别计算两个策略的EV ===
    # 策略1：买YES + 卖牛差（使用contracts_strategy1）
    calc_input_strategy1 = CalculationInput(
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
        Price_Option1=deribit_ctx.k1_ask_usd,   # 卖K1 Call，用Ask价
        Price_Option2=deribit_ctx.k2_bid_usd,   # 买K2 Call，用Bid价
        BTC_Price=deribit_ctx.spot,
        Slippage_Rate=pm_yes_slip_open,  # 策略1使用YES的滑点
        Margin_Requirement=0,  # 临时值，后面会更新
        Total_Investment=inv_base_usd,
        pme_params=PMEParams(),
        contracts=float(contracts_strategy1),  # 策略1使用对应的合约数
        days_to_expiry=float(deribit_ctx.T * 365.0),
    )

    result_strategy1 = main_calculation(
        calc_input_strategy1,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=poly_ctx.yes_price,
        calculate_greeks=False,
        bs_edge_threshold=0.03,
    )

    # 策略2：买NO + 买牛差（使用contracts_strategy2）
    calc_input_strategy2 = CalculationInput(
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
        Price_Option1=deribit_ctx.k1_ask_usd,  # 买K1 Call，用Ask价
        Price_Option2=deribit_ctx.k2_bid_usd,   # 卖K2 Call，用Bid价
        BTC_Price=deribit_ctx.spot,
        Slippage_Rate=pm_no_slip_open,  # 策略2使用NO的滑点
        Margin_Requirement=0,  # 临时值，后面会更新
        Total_Investment=inv_base_usd,
        pme_params=PMEParams(),
        contracts=float(contracts_strategy2),  # 策略2使用对应的合约数
        days_to_expiry=float(deribit_ctx.T * 365.0),
    )

    result_strategy2 = main_calculation(
        calc_input_strategy2,
        use_pme_margin=True,
        calculate_annualized=True,
        pm_yes_price=poly_ctx.yes_price,
        calculate_greeks=False,
        bs_edge_threshold=0.03,
    )

    # === 4. 提取两个策略的毛收益（Gross EV，未扣除成本）===
    gross_ev_strategy1 = float(result_strategy1.expected_pnl_strategy1.Total_Expected)
    gross_ev_strategy2 = float(result_strategy2.expected_pnl_strategy2.Total_Expected)

    # === 5. 分别计算两个策略的完整成本 ===
    # 策略1使用YES token的best_ask和best_bid
    costs_strategy1 = calculate_strategy_costs(
        strategy=1,
        inv_base_usd=inv_base_usd,
        contracts=contracts_strategy1,
        pm_shares=pm_yes_shares_open,
        pm_avg_open=pm_yes_avg_open,
        pm_avg_close=pm_yes_avg_close,
        best_ask=float(pm_yes_open["best_ask"]),  # 买入YES时的最优卖价
        best_bid=float(pm_yes_close["best_bid"]),  # 卖出YES时的最优买价
        deribit_costs=result_strategy1.deribit_costs_strategy1,
        deribit_ctx=deribit_ctx,
    )

    # 策略2使用NO token的best_ask和best_bid
    costs_strategy2 = calculate_strategy_costs(
        strategy=2,
        inv_base_usd=inv_base_usd,
        contracts=contracts_strategy2,
        pm_shares=pm_no_shares_open,
        pm_avg_open=pm_no_avg_open,
        pm_avg_close=pm_no_avg_close,
        best_ask=float(pm_no_open["best_ask"]),  # 买入NO时的最优卖价
        best_bid=float(pm_no_close["best_bid"]),  # 卖出NO时的最优买价
        deribit_costs=result_strategy2.deribit_costs_strategy2,
        deribit_ctx=deribit_ctx,
    )

    # === 6. 计算两个策略的净EV（毛收益 - 总成本）===
    net_ev_strategy1 = gross_ev_strategy1 - costs_strategy1.total_cost
    net_ev_strategy2 = gross_ev_strategy2 - costs_strategy2.total_cost

    # === 7. 选择净EV更高的策略 ===
    if net_ev_strategy1 > net_ev_strategy2:
        # 策略1净EV更高
        optimal_strategy = 1
        optimal_contracts = contracts_strategy1
        optimal_gross_ev = gross_ev_strategy1
        optimal_net_ev = net_ev_strategy1
        optimal_costs = costs_strategy1
        strategy_name = "买YES + 卖牛差"
        strategy_choice_reason = f"净EV ${net_ev_strategy1:.2f} > ${net_ev_strategy2:.2f} (差: ${net_ev_strategy1 - net_ev_strategy2:.2f})"

        # 策略1的实际数据
        pm_shares = pm_yes_shares_open
        pm_avg_open = pm_yes_avg_open
        pm_avg_close = pm_yes_avg_close
        pm_slip_open = pm_yes_slip_open
        pm_slip_close = pm_yes_slip_close
    else:
        # 策略2净EV更高或相等
        optimal_strategy = 2
        optimal_contracts = contracts_strategy2
        optimal_gross_ev = gross_ev_strategy2
        optimal_net_ev = net_ev_strategy2
        optimal_costs = costs_strategy2
        strategy_name = "买NO + 买牛差"
        strategy_choice_reason = f"净EV ${net_ev_strategy2:.2f} >= ${net_ev_strategy1:.2f} (差: ${net_ev_strategy2 - net_ev_strategy1:.2f})"

        # 策略2的实际数据
        pm_shares = pm_no_shares_open
        pm_avg_open = pm_no_avg_open
        pm_avg_close = pm_no_avg_close
        pm_slip_open = pm_no_slip_open
        pm_slip_close = pm_no_slip_close

    print(f"\n📊 策略比较:")
    print(f"  策略1（买YES + 卖牛差）:")
    print(f"    合约数: {contracts_strategy1:.6f}")
    print(f"    毛收益: ${gross_ev_strategy1:.2f}")
    print(f"    总成本: ${costs_strategy1.total_cost:.2f}")
    print(f"    净EV: ${net_ev_strategy1:.2f}")
    print(f"  策略2（买NO + 买牛差）:")
    print(f"    合约数: {contracts_strategy2:.6f}")
    print(f"    毛收益: ${gross_ev_strategy2:.2f}")
    print(f"    总成本: ${costs_strategy2.total_cost:.2f}")
    print(f"    净EV: ${net_ev_strategy2:.2f}")
    print(f"\n✅ 最优选择: 策略{optimal_strategy} ({strategy_name})")
    print(f"   选择原因: {strategy_choice_reason}")
    print(f"   预期净收益: ${optimal_net_ev:.2f}")
    print(f"   ROI: {(optimal_net_ev / (inv_base_usd + optimal_costs.im_usd) * 100):.2f}%")


    # === 8. 构造返回结果 ===
    # 只显示当前策略的 EV，另一个设为 0
    if optimal_strategy == 1:
        ev_display_yes = optimal_net_ev
        ev_display_no = 0.0
        total_costs_yes = optimal_costs.total_cost
        total_costs_no = 0.0
        open_cost_yes = optimal_costs.open_cost
        open_cost_no = 0.0
        holding_cost_yes = optimal_costs.holding_cost
        holding_cost_no = 0.0
        close_cost_yes = optimal_costs.close_cost
        close_cost_no = 0.0
        slippage_rate_used = pm_slip_open
    else:
        ev_display_yes = 0.0
        ev_display_no = optimal_net_ev
        total_costs_yes = 0.0
        total_costs_no = optimal_costs.total_cost
        open_cost_yes = 0.0
        open_cost_no = optimal_costs.open_cost
        holding_cost_yes = 0.0
        holding_cost_no = optimal_costs.holding_cost
        close_cost_yes = 0.0
        close_cost_no = optimal_costs.close_cost
        slippage_rate_used = pm_slip_open

    # 使用最优策略的 calc_input
    calc_input_for_result = calc_input_strategy1 if optimal_strategy == 1 else calc_input_strategy2

    result = InvestmentResult(
        investment=inv_base_usd,
        ev_yes=ev_display_yes,  # 净收益
        ev_no=ev_display_no,    # 净收益
        total_costs_yes=total_costs_yes,
        total_costs_no=total_costs_no,
        open_cost_yes=open_cost_yes,
        open_cost_no=open_cost_no,
        holding_cost_yes=holding_cost_yes,
        holding_cost_no=holding_cost_no,
        close_cost_yes=close_cost_yes,
        close_cost_no=close_cost_no,
        im_usd=optimal_costs.im_usd,
        im_btc=optimal_costs.im_btc,
        im_usd_strategy1=costs_strategy1.im_usd,
        im_usd_strategy2=costs_strategy2.im_usd,
        im_btc_strategy1=costs_strategy1.im_btc,
        im_btc_strategy2=costs_strategy2.im_btc,
        contracts=float(optimal_contracts),
        pm_yes_slippage=pm_yes_slip_open,
        pm_no_slippage=pm_no_slip_open,
        slippage_rate_used=slippage_rate_used,
        calc_input=calc_input_for_result,
        # === 保存两个策略的完整数据 ===
        net_ev_strategy1=net_ev_strategy1,
        net_ev_strategy2=net_ev_strategy2,
        gross_ev_strategy1=gross_ev_strategy1,
        gross_ev_strategy2=gross_ev_strategy2,
        contracts_strategy1=contracts_strategy1,
        contracts_strategy2=contracts_strategy2,
        total_cost_strategy1=costs_strategy1.total_cost,
        total_cost_strategy2=costs_strategy2.total_cost,
        # === 新增：两个策略的成本明细 ===
        open_cost_strategy1=costs_strategy1.open_cost,
        open_cost_strategy2=costs_strategy2.open_cost,
        holding_cost_strategy1=costs_strategy1.holding_cost,
        holding_cost_strategy2=costs_strategy2.holding_cost,
        close_cost_strategy1=costs_strategy1.close_cost,
        close_cost_strategy2=costs_strategy2.close_cost,
        # === PM市场价格详情（用于套利分析）===
        best_ask_strategy1=float(pm_yes_open["best_ask"]),
        best_bid_strategy1=float(pm_yes_close["best_bid"]),
        mid_price_strategy1=float(pm_yes_open["mid_price"]),
        spread_strategy1=float(pm_yes_open["spread"]),
        best_ask_strategy2=float(pm_no_open["best_ask"]),
        best_bid_strategy2=float(pm_no_close["best_bid"]),
        mid_price_strategy2=float(pm_no_open["mid_price"]),
        spread_strategy2=float(pm_no_open["spread"]),
    )

    return result, optimal_strategy


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
