from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from core.deribit_client import get_testnet_initial_margin, DeribitUserCfg
from core.polymarket_client import get_polymarket_slippage
from strategy.position_calculator import (
    PositionInputs,
    strategy1_position_contracts,
    strategy2_position_contracts,
)
from strategy.test_fixed import main_calculation, CalculationInput, PMEParams
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

    # === 2. 头寸与合约张数 ===
    pos_in = PositionInputs(
        inv_base_usd=inv_base_usd,
        call_k1_bid_btc=deribit_ctx.k1_bid_btc,
        call_k2_ask_btc=deribit_ctx.k2_ask_btc,
        call_k1_ask_btc=deribit_ctx.k1_ask_btc,
        call_k2_bid_btc=deribit_ctx.k2_bid_btc,
        btc_usd=deribit_ctx.spot,
    )

    contracts_s1, s1_income_usd = strategy1_position_contracts(pos_in)
    contracts_s2, s2_cost_usd = strategy2_position_contracts(
        pos_in, poly_no_entry=poly_ctx.no_price
    )
    amount_contracts = max(abs(contracts_s1), abs(contracts_s2))

    # === 3. Deribit 初始保证金 ===
    im_value_btc = float(
        await get_testnet_initial_margin(
            deribit_user_cfg,
            amount=amount_contracts,
            instrument_name=deribit_ctx.inst_k1,
        )
    )
    im_value_usd = im_value_btc * deribit_ctx.spot

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

    ev_yes = float(result.expected_pnl_strategy1.Total_Expected)
    ev_no = float(result.expected_pnl_strategy2.Total_Expected)
    total_costs_yes = float(result.costs.Total_Cost)
    total_costs_no = float(result.costs.Total_Cost)

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
