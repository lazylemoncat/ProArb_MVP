import pandas as pd

def earlt_exit_process_row(row):
    row["status"] = "close"
    strategy = row["strategy"]
    token_id = row["yes_token_id"] if strategy == 1 else row["no_token_id"]
    print(token_id)
    market_id = row["market_id"]
    return row

positions_csv = "./data/positions.csv"

csv_df = pd.read_csv(positions_csv)
csv_df = csv_df.apply(earlt_exit_process_row, axis=1)