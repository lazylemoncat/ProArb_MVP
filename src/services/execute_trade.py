import logging
from datetime import datetime, timezone

from ..fetch_data.deribit.deribit_client import DeribitMarketContext
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from ..telegram.TG_bot import TG_bot
from ..trading.deribit_trade import DeribitUserCfg
from ..trading.deribit_trade_client import Deribit_trade_client
from ..trading.polymarket_trade_client import Polymarket_trade_client
from ..utils.loadAllConfig import Env_config
from ..utils.save_position import save_position

logger = logging.getLogger(__name__)

# TODO 重构
async def execute_trade(
    trade_signal: bool,
    dry_run: bool,
    inv_usd: float,
    contract_amount: float,
    poly_ctx: PolymarketContext,
    deribit_ctx: DeribitMarketContext,
    strategy_choosed: int,
    env_config: Env_config,
    trading_bot: TG_bot,
    limit_price: float,
    token_id: str,
    fee_total: float,
    slippage_pct: float,
    net_ev: float,
    positions_csv: str,
    # 新增参数
    gross_ev: float,
    roi_pct: float,
    signal_id: str
):
    # 参数验证
    if not trade_signal:
        return False
    
    if inv_usd <= 0:
        assert False
    
    # yes_token_id = poly_ctx.yes_token_id
    # pm_open = await PolymarketClient.get_polymarket_slippage(
    #     yes_token_id,
    #     inv_usd,
    #     side="ask",
    #     amount_type="usd",
    # )
    # yes_avg_price = pm_open.avg_price
    # slippage_pct_1 = pm_open.slippage_pct
    
    # no_token_id = poly_ctx.no_token_id
    # pm_open = await PolymarketClient.get_polymarket_slippage(
    #     no_token_id,
    #     inv_usd,
    #     side="ask",
    #     amount_type="usd",
    # )
    # no_avg_price = pm_open.avg_price
    # slippage_pct_2 = pm_open.slippage_pct

    # pm_avg_open = yes_avg_price if strategy_choosed == 1 else no_avg_price
    # slippage_pct = slippage_pct_1 if strategy_choosed == 1 else slippage_pct_2
    # token_id = yes_token_id if strategy_choosed == 1 else no_token_id

    # if contract_amount < 0.1:
    #     assert False
    
    # # 获取实际成交价格
    # limit_price = round(pm_avg_open, 2)
    # # 获取 db 手续费, pm 没有手续费
    # db_fee = 0.0003 * float(deribit_ctx.spot) * contract_amount
    # k1_fee = 0.125 * (deribit_ctx.k1_ask_usd if strategy_choosed == 2 else deribit_ctx.k1_bid_usd) * contract_amount
    # k2_fee = 0.125 * (deribit_ctx.k2_bid_usd if strategy_choosed == 2 else deribit_ctx.k2_ask_usd) * contract_amount
    # fee_total = max(min(db_fee, k1_fee), min(db_fee, k2_fee))
    # # 获取滑点
    # slippage = inv_usd * slippage_pct
    # # 获取净利润
    # strategy_input = Strategy_input(
    #     inv_usd=inv_usd,
    #     strategy=strategy_choosed,
    #     spot_price=deribit_ctx.spot,
    #     k1_price=deribit_ctx.k1_strike,
    #     k2_price=deribit_ctx.k2_strike,
    #     k_poly_price=deribit_ctx.K_poly,
    #     days_to_expiry=deribit_ctx.days_to_expairy,
    #     sigma=deribit_ctx.mark_iv / 100.0,
    #     pm_yes_price=yes_avg_price,
    #     pm_no_price=no_avg_price,
    #     is_DST=datetime.now().dst() is not None,
    #     k1_ask_btc=deribit_ctx.k1_ask_btc,
    #     k1_bid_btc=deribit_ctx.k1_bid_btc,
    #     k2_ask_btc=deribit_ctx.k2_ask_btc,
    #     k2_bid_btc=deribit_ctx.k2_bid_btc
    # )
    # strategy_result = cal_strategy_result(strategy_input)
    # gross_ev = strategy_result.gross_ev
    # net_ev = gross_ev - fee_total - slippage

    # if net_ev <= 0:
    #     return False
    
    # prob_diff = (deribit_price - limit_price) * 100.0
    # prob_edge_pct = abs(prob_diff) / 100.0
    # trade_filter_input = Trade_filter_input(
    #     inv_usd=inv_usd,
    #     market_id=poly_ctx.market_id,
    #     contract_amount=contract_amount,
    #     pm_price=limit_price,
    #     net_ev=net_ev,
    #     roi_pct=roi_pct,
    #     prob_edge_pct=prob_edge_pct
    # )
    # trade_signal, trade_details = check_should_trade_signal(trade_filter_input, trade_filter)
    if not trade_signal:
        # await alert_bot.publish(str(trade_details))
        # logger.info(trade_details)
        print("# await alert_bot.publish(str(trade_details))")
        return False
    # 交易
    contract_amount = round(contract_amount, 1)
    await trading_bot.publish(f"{poly_ctx.market_id} 正在进行交易")
    pm_order_id = ""
    if not dry_run:
        deribit_cfg = DeribitUserCfg(
            user_id=env_config.deribit_user_id,
            client_id=env_config.deribit_client_id,
            client_secret=str(env_config.deribit_client_secret),
        )
        try:
            logger.info(f"limit_price: {limit_price}")
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
            logger.warning(f"db 交易: {sps}, {db_order_ids}, {executed_contracts}")
        except Exception:
            logger.error(f"db 交易失败, market_id: {poly_ctx.market_id}")
            raise Exception

    save_position(
        dry_run=dry_run,
        pm_ctx=poly_ctx,
        db_ctx=deribit_ctx,
        trade_id=str(pm_order_id),
        signal_id=signal_id,
        direction="no",
        status="open",
        strategy=strategy_choosed,
        pm_entry_cost=inv_usd,
        entry_price_pm=limit_price,
        contracts=contract_amount,
        dr_entry_cost=fee_total,
        expiry_timestamp=deribit_ctx.k1_expiration_timestamp,
        csv_path=positions_csv,
        slippage_pct=slippage_pct,
        gross_ev=gross_ev,
        net_ev=net_ev,
        roi_pct=roi_pct
    )
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
        logger.error(e, exc_info=True)
        raise e
    finally:
        # msg: str = (
        #     f"交易debug: {poly_ctx.event_title}, {poly_ctx.market_title}\n"
        #     f"strategy: {strategy_choosed}, spot_price: {deribit_ctx.spot}\n"
        #     f"trade_signal: {trade_signal}, dry_run: {dry_run}\n"
        #     f"inv_usd: {inv_usd}, contract_amount: {contract_amount}\n"
        #     f"yes_price: {yes_avg_price}, no_price: {no_avg_price}\n"
        #     f"k1_bid_btc: {deribit_ctx.k1_bid_btc}, k1_ask_btc: {deribit_ctx.k1_ask_btc}\n"
        #     f"k2_bid_btc: {deribit_ctx.k2_bid_btc}, k2_ask_btc: {deribit_ctx.k2_ask_btc}\n"
        #     f"mark_iv: {deribit_ctx.mark_iv}, sigma: {deribit_ctx.mark_iv / 100.0}\n"
        #     f"days_to_expairy: {deribit_ctx.days_to_expairy}, r: {deribit_ctx.r}\n"
        #     f"slippage_pct: {slippage_pct}, slippage: {slippage}, fee_total: {fee_total}\n"
        #     f"roi_pct: {roi_pct}, gross_ev: {gross_ev}, net_ev: {net_ev}\n"
        #     f"{datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}"
        # )
        # logger.info(msg)
        pass