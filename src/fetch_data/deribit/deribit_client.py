from dataclasses import dataclass
import time
from typing import Any, Literal

from ...strategy.probability_engine import bs_probability_gt

from .deribit_api import DeribitAPI

@dataclass
class DeribitMarketContext:
    """聚合 Deribit 相关的行情与参数，方便后续计算和输出。"""
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
    k1_fee_approx: float
    k2_fee_approx: float
    mark_iv: float
    # 时间与概率
    k1_expiration_timestamp: float
    T: float
    days_to_expairy: float
    r: float
    deribit_prob: float


@dataclass
class Deribit_option_data:
    instrument_name: str
    mark_iv: float
    bid_price: float
    ask_price: float
    fee: float

class DeribitClient:
    @staticmethod
    def get_db_context(
        title: str, 
        asset: str, 
        inst_k1: str, 
        inst_k2: str, 
        k1_strike: float, 
        k2_strike: float,
        k_poly: float,
        expiry_timestamp: float
    ):
        asset = asset.upper()
        spot_symbol = "btc_usd" if asset == "BTC" else "eth_usd"
        spot = DeribitAPI.get_spot_price(spot_symbol)
        deribit_list = DeribitClient.get_deribit_option_data()
        k1_info = next((d for d in deribit_list if d.instrument_name == inst_k1), None)
        k2_info = next((d for d in deribit_list if d.instrument_name == inst_k2), None)
        if k1_info is None or k2_info is None:
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
        k1_fee_approx = float(k1_info.fee)
        k2_fee_approx = float(k2_info.fee)

        def _choose_mark_iv(k1_iv: float, k2_iv: float) -> float:
            """根据 PRD 约定选择用于定价的 sigma."""
            if k1_iv > 0:
                return k1_iv
            if k2_iv > 0:
                return k2_iv
            raise ValueError("Both K1 / K2 IV are non-positive, cannot choose mark_iv")

        mark_iv = _choose_mark_iv(k1_iv, k2_iv)

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

        return DeribitMarketContext(
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
            k1_expiration_timestamp=k1_exp,
            T=T,
            days_to_expairy=T * 365,
            r=r,
            deribit_prob=deribit_prob,
        )

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