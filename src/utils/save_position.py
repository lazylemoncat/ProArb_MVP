from dataclasses import dataclass, asdict
from datetime import datetime
from .CsvHandler import CsvHandler
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from ..fetch_data.deribit.deribit_client import DeribitMarketContext

@dataclass
class SavePosition:
    entry_timestamp: datetime
    dry_run: bool

    trade_id: str
    direction: str
    status: str
    strategy: int

    pm_entry_cost: float
    entry_price_pm: float

    contracts: float
    dr_entry_cost: float
    expiry_timestamp: float

    event_title: str
    market_title: str

    event_id: str
    market_id: str

    yes_price: float
    no_price: float

    yes_token_id: str
    no_token_id: str

    yes_bid_price_1: float
    yes_bid_price_size_1: float
    yes_bid_price_2: float
    yes_bid_price_size_2: float
    yes_bid_price_3: float
    yes_bid_price_size_3: float

    yes_ask_price_1: float
    yes_ask_price_1_size: float
    yes_ask_price_2: float
    yes_ask_price_2_size: float
    yes_ask_price_3: float
    yes_ask_price_3_size: float

    no_bid_price_1: float
    no_bid_price_size_1: float
    no_bid_price_2: float
    no_bid_price_size_2: float
    no_bid_price_3: float
    no_bid_price_size_3: float

    no_ask_price_1: float
    no_ask_price_1_size: float
    no_ask_price_2: float
    no_ask_price_2_size: float
    no_ask_price_3: float
    no_ask_price_3_size: float

    asset: str
    # 现货价格
    spot: float
    # 合约名称
    inst_k1: str
    inst_k2: str
    # k1 k2 代表的价格
    k1_strike: float
    k2_strike: float
    K_poly: float
    # BTC 计价
    k1_bid_btc: float
    k1_ask_btc: float
    k2_bid_btc: float
    k2_ask_btc: float
    k1_mid_btc: float
    k2_mid_btc: float
    # USD 计价
    k1_bid_usd: float
    k1_ask_usd: float
    k2_bid_usd: float
    k2_ask_usd: float
    k1_mid_usd: float
    k2_mid_usd: float
    # 波动率 / 手续费
    k1_iv: float
    k2_iv: float
    spot_iv_lower: tuple
    spot_iv_upper: tuple
    k1_fee_approx: float
    k2_fee_approx: float
    mark_iv: float
    # 时间与概率
    k1_expiration_timestamp: float
    T: float
    days_to_expairy: float
    r: float
    deribit_prob: float
    # asks & bids
    k1_ask_1_usd: list
    k1_ask_2_usd: list
    k1_ask_3_usd: list
    k2_ask_1_usd: list
    k2_ask_2_usd: list
    k2_ask_3_usd: list

    k1_bid_1_usd: list
    k1_bid_2_usd: list
    k1_bid_3_usd: list
    k2_bid_1_usd: list
    k2_bid_2_usd: list
    k2_bid_3_usd: list

def save_position(
        dry_run: bool,
        pm_ctx: PolymarketContext, 
        db_ctx: DeribitMarketContext, 
        trade_id: str,
        direction: str,
        status: str,
        strategy: int,
        pm_entry_cost: float,
        entry_price_pm: float,
        contracts: float,
        dr_entry_cost: float,
        expiry_timestamp: float,
        csv_path: str
    ):
    row_obj = SavePosition(
        entry_timestamp=pm_ctx.time,
        dry_run=dry_run,
        trade_id=trade_id,
        direction=direction,
        status=status,
        strategy=strategy,
        pm_entry_cost=pm_entry_cost,
        entry_price_pm=entry_price_pm,
        contracts=contracts,
        dr_entry_cost=dr_entry_cost,
        expiry_timestamp=expiry_timestamp,
        event_title=pm_ctx.event_title,
        market_title=pm_ctx.market_title,
        event_id=pm_ctx.event_id,
        market_id=pm_ctx.market_id,
        yes_price=pm_ctx.yes_price,
        no_price=pm_ctx.no_price,

        yes_token_id=pm_ctx.yes_token_id,
        no_token_id=pm_ctx.no_token_id,

        yes_bid_price_1=pm_ctx.yes_bid_price_1,
        yes_bid_price_size_1=pm_ctx.yes_bid_price_size_1,
        yes_bid_price_2=pm_ctx.yes_bid_price_2,
        yes_bid_price_size_2=pm_ctx.yes_bid_price_size_2,
        yes_bid_price_3=pm_ctx.yes_bid_price_3,
        yes_bid_price_size_3=pm_ctx.yes_bid_price_size_3,

        yes_ask_price_1=pm_ctx.yes_ask_price_1,
        yes_ask_price_1_size=pm_ctx.yes_ask_price_1_size,
        yes_ask_price_2=pm_ctx.yes_ask_price_2,
        yes_ask_price_2_size=pm_ctx.yes_ask_price_2_size,
        yes_ask_price_3=pm_ctx.yes_ask_price_3,
        yes_ask_price_3_size=pm_ctx.yes_ask_price_3_size,

        no_bid_price_1=pm_ctx.no_bid_price_1,
        no_bid_price_size_1=pm_ctx.no_bid_price_size_1,
        no_bid_price_2=pm_ctx.no_bid_price_2,
        no_bid_price_size_2=pm_ctx.no_bid_price_size_2,
        no_bid_price_3=pm_ctx.no_bid_price_3,
        no_bid_price_size_3=pm_ctx.no_bid_price_size_3,

        no_ask_price_1=pm_ctx.no_ask_price_1,
        no_ask_price_1_size=pm_ctx.no_ask_price_1_size,
        no_ask_price_2=pm_ctx.no_ask_price_2,
        no_ask_price_2_size=pm_ctx.no_ask_price_2_size,
        no_ask_price_3=pm_ctx.no_ask_price_3,
        no_ask_price_3_size=pm_ctx.no_ask_price_3_size,

        asset=db_ctx.asset,
        spot=db_ctx.spot,
        inst_k1=db_ctx.inst_k1,
        inst_k2=db_ctx.inst_k2,
        k1_strike=db_ctx.k1_strike,
        k2_strike=db_ctx.k2_strike,
        K_poly=db_ctx.K_poly,

        k1_bid_btc=db_ctx.k1_bid_btc,
        k1_ask_btc=db_ctx.k1_ask_btc,
        k2_bid_btc=db_ctx.k2_bid_btc,
        k2_ask_btc=db_ctx.k2_ask_btc,
        k1_mid_btc=db_ctx.k1_mid_btc,
        k2_mid_btc=db_ctx.k2_mid_btc,

        k1_bid_usd=db_ctx.k1_bid_usd,
        k1_ask_usd=db_ctx.k1_ask_usd,
        k2_bid_usd=db_ctx.k2_bid_usd,
        k2_ask_usd=db_ctx.k2_ask_usd,
        k1_mid_usd=db_ctx.k1_mid_usd,
        k2_mid_usd=db_ctx.k2_mid_usd,

        k1_iv=db_ctx.k1_iv,
        k2_iv=db_ctx.k2_iv,
        spot_iv_lower=db_ctx.spot_iv_lower,
        spot_iv_upper=db_ctx.spot_iv_upper,
        k1_fee_approx=db_ctx.k1_fee_approx,
        k2_fee_approx=db_ctx.k2_fee_approx,
        mark_iv=db_ctx.mark_iv,

        k1_expiration_timestamp=db_ctx.k1_expiration_timestamp,
        T=db_ctx.T,
        days_to_expairy=db_ctx.days_to_expairy,
        r=db_ctx.r,
        deribit_prob=db_ctx.deribit_prob,

        k1_ask_1_usd=db_ctx.k1_ask_1_usd,
        k1_ask_2_usd=db_ctx.k1_ask_2_usd,
        k1_ask_3_usd=db_ctx.k1_ask_3_usd,
        k2_ask_1_usd=db_ctx.k2_ask_1_usd,
        k2_ask_2_usd=db_ctx.k2_ask_2_usd,
        k2_ask_3_usd=db_ctx.k2_ask_3_usd,

        k1_bid_1_usd=db_ctx.k1_bid_1_usd,
        k1_bid_2_usd=db_ctx.k1_bid_2_usd,
        k1_bid_3_usd=db_ctx.k1_bid_3_usd,
        k2_bid_1_usd=db_ctx.k2_bid_1_usd,
        k2_bid_2_usd=db_ctx.k2_bid_2_usd,
        k2_bid_3_usd=db_ctx.k2_bid_3_usd,
    )

    CsvHandler.save_to_csv(csv_path, row_dict=asdict(row_obj), class_obj=SavePosition)

    return row_obj
