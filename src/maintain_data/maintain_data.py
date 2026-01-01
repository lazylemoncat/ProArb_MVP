import pandas as pd
from .ev import maintain_ev

async def maintain_data():
    ev_path = "./data/ev.csv"
    position_df = pd.read_csv("./data/positions.csv")

    for row in position_df.itertuples(index=False):
        tread_id = row.trade_id
        await maintain_ev(ev_path, str(tread_id), position_df)