import csv

def save_result_csv(row: dict, csv_path: str="data/results.csv"):
    """
    保存结果到 CSV
    Args:
        row: 待保存的单行数据
        csv_path: 输出的 csv 文件地址
    """
    header = list(row.keys())
    try:
        with open(csv_path, "x", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)
    except FileExistsError:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writerow(row)