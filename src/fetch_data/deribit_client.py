from dataclasses import dataclass
from typing import Literal

from .deribit_api import DeribitAPI

@dataclass
class Deribit_option_data:
    instrument_name: str
    mark_iv: float
    bid_price: float
    ask_price: float
    settlement_currency: str
    fee: float

class DeribitClient:
    @staticmethod
    def get_deribit_option_data(
        currency: str = "BTC",
        kind: str = "option",
        settlement_currency: str | None = "USDC",
        base_fee_btc: float = 0.0003,
        base_fee_eth: float = 0.0003,
        usdc_settled: bool = True,
        amount: float = 1.0,
    ):
        data = DeribitAPI.get_deribit_option_data(
            currency=currency, kind=kind, settlement_currency=settlement_currency
        )
        results: list[Deribit_option_data] = []
        for item in data.get("result", []):
            try:
                option_name = str(item.get("instrument_name"))
                mark_iv = float(item.get("mark_iv"))
                bid_price = float(item.get("bid_price"))
                ask_price = float(item.get("ask_price"))
                option_price = float(item.get("last") or 0.0)
                index_price = float(item.get("underlying_price"))
                settlement = str(item.get("settlement_currency") or "").upper() or "BTC"

                is_usdc_settled = settlement == "USDC" if settlement_currency else usdc_settled

                # 手续费计算逻辑
                if not is_usdc_settled:
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
                        settlement_currency=settlement,
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
        settlement_currency: Literal["BTC", "USDC"] | None = "USDC",
    ):
        return DeribitAPI.find_option_instrument(
            strike=strike,
            currency=currency,
            call=call,
            day_offset=day_offset,
            exp_timestamp=exp_timestamp,
            settlement_currency=settlement_currency,
        )
