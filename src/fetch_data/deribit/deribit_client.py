import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import websockets

from ...strategy.probability_engine import bs_probability_gt
from .deribit_api import DeribitAPI, DeribitUserCfg
import logging

logger = logging.getLogger(__name__)

WS_URL = "wss://www.deribit.com/ws/api/v2"

@dataclass
class DeribitMarketContext:
    """聚合 Deribit 相关的行情与参数，方便后续计算和输出。"""
    time: datetime
    title: str
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

@dataclass
class Deribit_option_data:
    instrument_name: str
    mark_iv: float
    bid_price: float
    ask_price: float
    fee: float

def nearest_two_by_step(x: float, step: int = 1000):
    lower = math.floor(x / step) * step
    upper = lower + step
    # 找到最靠近 x 的数
    dl = abs(x - lower)
    du = abs(upper - x)

    # 等距时默认选 lower
    nearest = lower if dl <= du else upper
    return lower, upper, nearest


class DeribitClient:
    @staticmethod
    async def get_orderbook_prices(
        deribitUserCfg: DeribitUserCfg,
        instrument_name: str,
        depth: int = 3
    ):
        async with websockets.connect(WS_URL) as websocket:
            await DeribitAPI.websocket_auth(websocket, deribitUserCfg)
            orderbook = await DeribitAPI.get_orderbook_by_instrument_name(
                websocket,
                deribitUserCfg,
                instrument_name,
                depth=depth
            )
            res = orderbook.get("result", {})
            return {
                "bids": res.get("bids", []),
                "asks": res.get("asks", []),
            }
    
    @staticmethod
    async def get_db_context(
        deribitUserCfg: DeribitUserCfg,
        title: str, 
        asset: Literal["BTC", "ETH"], 
        k1_strike: float, 
        k2_strike: float,
        k_poly: float,
        expiry_timestamp: float,
        day_offset: int
    ):
        try:
            spot_symbol = "btc_usd" if asset == "BTC" else "eth_usd"
            spot = DeribitAPI.get_spot_price(spot_symbol)
            deribit_list = DeribitClient.get_deribit_option_data()
            spot_lower, spot_upper, nearest = nearest_two_by_step(spot, step=1000)
            inst_k1, k1_exp = DeribitClient.find_option_instrument(
                k1_strike,
                call=True,
                currency=asset,
                day_offset=day_offset,
            )
            inst_k2, k2_exp = DeribitClient.find_option_instrument(
                k2_strike,
                call=True,
                currency=asset,
                day_offset=day_offset,
            )
            k1_info = next((d for d in deribit_list if d.instrument_name == inst_k1), None)
            k2_info = next((d for d in deribit_list if d.instrument_name == inst_k2), None)
            inst_lower, _ = DeribitClient.find_option_instrument(
                spot_lower,
                call=True,
                currency=asset,
                exp_timestamp=expiry_timestamp,
            )
            inst_upper, _ = DeribitClient.find_option_instrument(
                spot_upper,
                call=True,
                currency=asset,
                exp_timestamp=expiry_timestamp,
            )
            spot_lower_info = next((d for d in deribit_list if d.instrument_name == inst_lower), None)
            spot_upper_info = next((d for d in deribit_list if d.instrument_name == inst_upper), None)
            if k1_info is None or k2_info is None or spot_lower_info is None or spot_upper_info is None:
                raise RuntimeError("missing deribit option quotes")

            k1_bid_btc = float(k1_info.bid_price)
            k1_ask_btc = float(k1_info.ask_price)
            k2_bid_btc = float(k2_info.bid_price)
            k2_ask_btc = float(k2_info.ask_price)
            k1_mid_btc = (k1_bid_btc + k1_ask_btc) / 2.0
            k2_mid_btc = (k2_bid_btc + k2_ask_btc) / 2.0

            # === 转为 USD，方便后续风控 / 收益计算 ===
            k1_bid_usd = k1_bid_btc * spot
            k1_ask_usd = k1_ask_btc * spot
            k2_bid_usd = k2_bid_btc * spot
            k2_ask_usd = k2_ask_btc * spot
            k1_mid_usd = k1_mid_btc * spot
            k2_mid_usd = k2_mid_btc * spot

            k1_iv = float(k1_info.mark_iv)
            k2_iv = float(k2_info.mark_iv)
            spot_iv_lower = float(spot_lower_info.mark_iv)
            spot_iv_upper = float(spot_upper_info.mark_iv)
            k1_fee_approx = float(k1_info.fee)
            k2_fee_approx = float(k2_info.fee)

            def _choose_mark_iv(
                    spot_lower: float, 
                    spot_iv_lower: float, 
                    spot_upper: float, 
                    spot_iv_upper: float, 
                    nearest: float
            ) -> float:
                """选择最靠近 spot 的 mark_iv"""
                return spot_iv_lower if nearest == spot_lower else spot_iv_upper

            mark_iv = _choose_mark_iv(spot_lower, spot_iv_lower, spot_upper, spot_iv_upper, nearest)

            inst_k1, k1_exp = DeribitClient.find_option_instrument(
                k1_strike,
                call=True,
                currency="BTC",
                exp_timestamp=expiry_timestamp
            )
            inst_k2, k2_exp = DeribitClient.find_option_instrument(
                k2_strike,
                call=True,
                currency="BTC",
                exp_timestamp=expiry_timestamp
            )

            # 天化到期时间 T
            now_ms = time.time() * 1000.0
            T = (k1_exp - now_ms) / (365.0 * 24.0 * 60.0 * 60.0 * 1000.0)
            T = max(T, 0.0)
            r = 0.05

            deribit_prob = bs_probability_gt(
                S=spot, K=k_poly, T=T, sigma=mark_iv / 100.0, r=r
            )

            orderbook_k1 = await DeribitClient.get_orderbook_prices(deribitUserCfg, inst_k1)
            orderbook_k2 = await DeribitClient.get_orderbook_prices(deribitUserCfg, inst_k2)

            k1_asks = orderbook_k1.get("asks", [])
            k1_bids = orderbook_k1.get("bids", [])

            k2_asks = orderbook_k2.get("asks", [])
            k2_bids = orderbook_k2.get("bids", [])

            return DeribitMarketContext(
                time=datetime.now(timezone.utc),
                title=title,
                asset=asset,
                spot=spot,
                inst_k1=inst_k1,
                inst_k2=inst_k2,
                k1_strike=k1_strike,
                k2_strike=k2_strike,
                K_poly=k_poly,
                k1_bid_btc=k1_bid_btc,
                k1_ask_btc=k1_ask_btc,
                k2_bid_btc=k2_bid_btc,
                k2_ask_btc=k2_ask_btc,
                k1_mid_btc=k1_mid_btc,
                k2_mid_btc=k2_mid_btc,
                k1_bid_usd=k1_bid_usd,
                k1_ask_usd=k1_ask_usd,
                k2_bid_usd=k2_bid_usd,
                k2_ask_usd=k2_ask_usd,
                k1_mid_usd=k1_mid_usd,
                k2_mid_usd=k2_mid_usd,
                k1_iv=k1_iv,
                k2_iv=k2_iv,
                k1_fee_approx=k1_fee_approx,
                k2_fee_approx=k2_fee_approx,
                mark_iv=mark_iv,
                spot_iv_lower=(spot_lower, spot_iv_lower),
                spot_iv_upper=(spot_upper, spot_iv_upper),
                k1_expiration_timestamp=k1_exp,
                T=T,
                days_to_expairy=T * 365,
                r=r,
                deribit_prob=deribit_prob,
                k1_ask_1_usd=k1_asks[0] if len(k1_asks) >= 1 else [0, 0],
                k1_ask_2_usd=k1_asks[1] if len(k1_asks) >= 2 else [0, 0],
                k1_ask_3_usd=k1_asks[2] if len(k1_asks) >= 3 else [0, 0],
                k2_ask_1_usd=k2_asks[0] if len(k2_asks) >= 1 else [0, 0],
                k2_ask_2_usd=k2_asks[1] if len(k2_asks) >= 2 else [0, 0],
                k2_ask_3_usd=k2_asks[2] if len(k2_asks) >= 3 else [0, 0],

                k1_bid_1_usd=k1_bids[0] if len(k1_bids) >= 1 else [0, 0],
                k1_bid_2_usd=k1_bids[1] if len(k1_bids) >= 2 else [0, 0],
                k1_bid_3_usd=k1_bids[2] if len(k1_bids) >= 3 else [0, 0],
                k2_bid_1_usd=k2_bids[0] if len(k2_bids) >= 1 else [0, 0],
                k2_bid_2_usd=k2_bids[1] if len(k2_bids) >= 2 else [0, 0],
                k2_bid_3_usd=k2_bids[2] if len(k2_bids) >= 3 else [0, 0],
            )
        except Exception as e:
            logger.warning(e, exc_info=True)
            raise e

    @staticmethod
    def get_deribit_option_data(
        currency: str = "BTC",
        kind: str = "option",
        base_fee_btc: float = 0.0003,
        base_fee_eth: float = 0.0003,
        usdc_settled: bool = False,
        amount: float = 1.0,
    ):
        data = DeribitAPI.get_deribit_option_data(currency=currency, kind=kind)
        results: list[Deribit_option_data] = []
        for item in data.get("result", []):
            try:
                option_name = str(item.get("instrument_name"))
                mark_iv = float(item.get("mark_iv"))
                bid_price = float(item.get("bid_price"))
                ask_price = float(item.get("ask_price"))
                option_price = float(item.get("last") or 0.0)
                index_price = float(item.get("underlying_price"))

                # 手续费计算逻辑
                if not usdc_settled:
                    base_fee = base_fee_btc if currency.upper() == "BTC" else base_fee_eth
                    fee = max(base_fee, 0.125 * option_price) * amount
                else:
                    fee = max(0.0003 * index_price, 0.125 * option_price) * amount

                results.append(
                    Deribit_option_data(
                        instrument_name=option_name, 
                        mark_iv=mark_iv, 
                        bid_price=bid_price, 
                        ask_price=ask_price, 
                        fee=fee
                    )
                )
            except (TypeError, ValueError):
                # 某条脏数据就直接跳过
                continue

        return results
    
    @staticmethod
    def find_option_instrument(
        strike: float,
        currency: Literal["BTC", "ETH"] = "BTC",
        call: bool = True,
        day_offset: int = 0,
        exp_timestamp: float | None = None,
    ):
        return DeribitAPI.find_option_instrument(
            strike=strike, 
            currency=currency, 
            call=call, 
            day_offset=day_offset, 
            exp_timestamp=exp_timestamp
        )
    
    @staticmethod
    def get_delivery_price(
        currency: Literal["BTC", "ETH"] = "BTC",
        count: int = 1,
    ) -> dict[str, Any]:
        return DeribitAPI.get_delivery_price(currency=currency, count=count)
    
    @staticmethod
    def get_spot_price(index_name: Literal["btc_usd", "eth_usd"] = "btc_usd"):
        return DeribitAPI.get_spot_price(index_name)