import logging
from datetime import datetime, timezone

from ..filters.filters import Trade_filter_input, check_should_trade_signal, Trade_filter

from ..fetch_data.polymarket_client import PolymarketClient
from ..strategy.strategy2 import Strategy_input, cal_strategy_result
from ..telegram.TG_bot import TG_bot
from ..trading.deribit_trade import DeribitUserCfg
from ..trading.deribit_trade_client import Deribit_trade_client
from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..utils.dataloader import Env_config
from ..utils.market_context import DeribitMarketContext, PolymarketState

logger = logging.getLogger(__name__)

async def send_opportunity(
        alert_bot, 
        market_title: str, 
        net_ev: float, 
        strategy: int,
        prob_diff: float,
        pm_price: float,
        deribit_price: float,
        inv_base_usd: float,
    ):
    try:
        now_ts = datetime.now(timezone.utc)

        await alert_bot.publish((
                f"{market_title} | EV: +${round(net_ev, 3)}\n"
                f"策略{strategy}, 概率差{round(prob_diff, 3)}\n"
                f"PM ${pm_price}, Deribit ${round(deribit_price, 3)}\n"
                f"建议投资${inv_base_usd}\n"
                f"{now_ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")}"
            ))
    except Exception as exc:
        logger.warning("Failed to publish Telegram opportunity notification: %s", exc, exc_info=True)

async def execute_trade(
    trade_signal: bool, 
    dry_run: bool,
    inv_usd: float,
    contract_amount: float,
    poly_ctx: PolymarketState, 
    deribit_ctx: DeribitMarketContext,
    strategy_choosed: int,
    env_config: Env_config,
    trading_bot: TG_bot,
    alert_bot: TG_bot,
    prob_diff: float,
    deribit_price: float,
    roi_pct: float,
    trade_filter: Trade_filter
):
    # 参数验证
    if not trade_signal:
        return False
    
    if inv_usd <= 0:
        assert False
    
    if strategy_choosed == 1:
        token_id = poly_ctx.yes_token_id
        pm_open = await PolymarketClient.get_polymarket_slippage(
            token_id,
            inv_usd,
            side="buy",
            amount_type="usd",
        )
        pm_avg_open = pm_open.avg_price
        slippage_pct = pm_open.slippage_pct
        
    elif strategy_choosed == 2:
        token_id = poly_ctx.no_token_id
        pm_open = await PolymarketClient.get_polymarket_slippage(
            token_id,
            inv_usd,
            side="buy",
            amount_type="usd",
        )
        pm_avg_open = pm_open.avg_price
        slippage_pct = pm_open.slippage_pct
    else:
        assert False

    if contract_amount < 0.1:
        assert False
    
    # 获取实际成交价格
    limit_price = pm_avg_open
    # 获取 db 手续费, pm 没有手续费
    db_fee = 0.003 * float(deribit_ctx.spot) * contract_amount
    k1_fee = 0.125 * (deribit_ctx.k1_ask_usd if strategy_choosed == 2 else deribit_ctx.k1_bid_usd) * contract_amount
    k2_fee = 0.125 * (deribit_ctx.k2_bid_usd if strategy_choosed == 2 else deribit_ctx.k2_ask_usd) * contract_amount
    fee_total = max(min(db_fee, k1_fee), min(db_fee, k2_fee))
    # 获取滑点
    slippage = inv_usd * slippage_pct
    # 获取净利润
    strategy_input = Strategy_input(
        inv_usd=inv_usd,
        strategy=strategy_choosed,
        spot_price=deribit_ctx.spot,
        k1_price=deribit_ctx.k1_strike,
        k2_price=deribit_ctx.k2_strike,
        k_poly_price=deribit_ctx.K_poly,
        days_to_expiry=deribit_ctx.days_to_expairy,
        sigma=deribit_ctx.mark_iv / 100.0,
        pm_yes_price=poly_ctx.yes_price,
        pm_no_price=poly_ctx.no_price,
        is_DST=datetime.now().dst() is not None,
        k1_ask_btc=deribit_ctx.k1_ask_btc,
        k1_bid_btc=deribit_ctx.k1_bid_btc,
        k2_ask_btc=deribit_ctx.k2_ask_btc,
        k2_bid_btc=deribit_ctx.k2_bid_btc
    )
    gross_ev = cal_strategy_result(strategy_input).gross_ev
    net_ev = gross_ev - fee_total - slippage
    if net_ev <= 0:
        return False
    await send_opportunity(
        alert_bot, 
        poly_ctx.market_title, 
        net_ev, 
        strategy_choosed, 
        prob_diff, 
        limit_price, 
        deribit_price, 
        inv_usd,
    )
    prob_diff = (deribit_price - limit_price) * 100.0
    prob_edge_pct = abs(prob_diff) / 100.0
    trade_filter_input = Trade_filter_input(
        inv_usd=inv_usd,
        market_id=poly_ctx.market_id,
        contract_amount=contract_amount,
        pm_price=limit_price,
        net_ev=net_ev,
        roi_pct=roi_pct,
        prob_edge_pct=prob_edge_pct
    )
    trade_signal, trade_details = check_should_trade_signal(trade_filter_input, trade_filter)
    if not trade_signal:
        logger.info(trade_details)
        return False
    # 交易
    await trading_bot.publish(f"{poly_ctx.market_id} 正在进行交易")
    if not dry_run:
        deribit_cfg = DeribitUserCfg(
            user_id=env_config.deribit_user_id,
            client_id=env_config.deribit_client_id,
            client_secret=str(env_config.deribit_client_secret),
        )
        try:
            pm_resp, pm_order_id = Polymarket_trade_client.place_buy_by_investment(
                token_id=token_id, investment_usd=inv_usd, limit_price=limit_price
            )
        except Exception:
            logger.error(f"pm 交易失败, market_id: {poly_ctx.market_id}")
            raise Exception
        try:
            sps, db_order_ids, executed_contracts = await Deribit_trade_client.execute_vertical_spread(
                deribit_cfg,
                contracts=contract_amount,
                inst_k1=deribit_ctx.inst_k1,
                inst_k2=deribit_ctx.inst_k2,
                strategy=strategy_choosed,
            )
        except Exception:
            logger.error(f"db 交易失败, market_id: {poly_ctx.market_id}")
            raise Exception
    # 通知
    try:
        await trading_bot.publish((
            "交易已执行\n"
            "类型： 开仓\n"
            f"策略{strategy_choosed}\n"
            f"模拟:{dry_run}\n"
            f"市场: {poly_ctx.market_title} {poly_ctx.event_title}, market id: {poly_ctx.market_id}\n"
            f"PM: 买入 {"YES" if strategy_choosed == 1 else "NO"} ${float(limit_price)}({inv_usd})\n"
            f"Deribit: {"卖出牛差" if strategy_choosed == 1 else "买入牛差"} {float(deribit_ctx.k1_strike)}-{float(deribit_ctx.k2_strike)}({float(contract_amount)})\n"
            f"手续费: ${round(float(fee_total), 3)}, 滑点:{float(inv_usd * slippage_pct)}\n"
            # 固定 gas 费 0.1
            # f"开仓成本{round(float(fee_total), 3) + 0.1}, 保证金:{round(float(result.im_usd), 3)}\n"
            f"预期净收益:{round(float(net_ev), 3)}\n"
            f"{datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}"
        ))
    except Exception as e:
        logger.error(e)
        raise e