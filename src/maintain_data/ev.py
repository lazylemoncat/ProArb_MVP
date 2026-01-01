from dataclasses import asdict, dataclass, fields
from typing import List, Type
from ..api.models import EVResponse
from pandas import DataFrame
import pandas as pd
from ..utils.CsvHandler import CsvHandler

def pydantic_field_names(model_cls: Type) -> List[str]:
    """
    Return field names for a Pydantic BaseModel (supports Pydantic v1 and v2).
    """
    # Pydantic v2
    if hasattr(model_cls, "model_fields"):
        return list(model_cls.model_fields.keys())

    raise TypeError(f"{model_cls} is not a supported Pydantic model class")

async def maintain_ev(ev_path: str, signal_id: str, position_df: DataFrame):
    expected_columns = pydantic_field_names(EVResponse)
    CsvHandler.check_csv(ev_path, expected_columns=expected_columns)

    df = pd.read_csv(ev_path)
    idx = df.index[df["signal_id"] == signal_id].tolist()
    
    if len(idx) != 0:
        return

    index = position_df.index[position_df["trade_id"] == signal_id].tolist()[0]
    pos_row = position_df.loc[index]

    ev_data = EVResponse(
        signal_id=pos_row["trade_id"],
        timestamp=pos_row["entry_timestamp"],
        market_title=pos_row["event_title"], # TODO 改为 market_title
        strategy=pos_row["strategy"],
        direction=str(pos_row["direction"]).upper(),
        target_usd=pos_row["pm_entry_cost"],
        k_poly=pos_row["K_poly"],
        dr_k1_strike=pos_row["k1_strike"],
        dr_k2_strike=pos_row["k2_strike"],
        dr_index_price=pos_row["spot"],
        days_to_expiry=pos_row["days_to_expairy"],
        pm_yes_avg_price=pos_row["yes_price"],
        pm_no_avg_price=pos_row["no_price"],
        pm_shares=0, # TODO
        pm_slippage_usd=0, #TODO
        dr_contracts=pos_row["contracts"],
        dr_k1_price=0, # TODO
        dr_k2_price=0, # TODO
        dr_iv=pos_row["mark_iv"],
        dr_k1_iv=pos_row["k1_iv"],
        dr_k2_iv=pos_row["k2_iv"],
        dr_iv_floor=pos_row["spot_iv_lower"][1],
        dr_iv_celling=pos_row["spot_iv_upper"][1],
        dr_prob=pos_row["deribit_prob"],
        ev_gross_usd=0, # TODO
        ev_theta_adj_usd=0, # TODO
        ev_model_usd=0, # TODO
        roi_model_pct=0, # TODO
    )
    row_data = ev_data.model_dump() if hasattr(ev_data, "model_dump") else ev_data.dict()
    new_row = pd.Series(row_data).reindex(df.columns)

    df.loc[len(df)] = new_row
    df.to_csv(ev_path, index=False)