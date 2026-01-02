import pandas as pd
from dataclasses import fields

from .ev import maintain_ev
from ..utils.CsvHandler import CsvHandler
from ..utils.save_position import SavePosition

async def maintain_data():
    ev_path = "./data/ev.csv"
    positions_csv = "./data/positions.csv"

    # 检查并确保 positions.csv 包含所有必需的列
    positions_columns = [f.name for f in fields(SavePosition)]
    CsvHandler.check_csv(positions_csv, positions_columns, fill_value="")

    position_df = pd.read_csv(positions_csv)

    for row in position_df.itertuples(index=False):
        tread_id = row.trade_id
        await maintain_ev(ev_path, str(tread_id), position_df)