from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict


def save_result_csv(row: Dict[str, Any], csv_path: str = "data/results.csv") -> None:
    """
    保存结果到 CSV 文件。如果文件不存在则写入表头，否则直接追加行。

    Args:
        row: 待保存的单行数据（key 为列名）
        csv_path: 输出的 csv 文件路径
    """
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = list(row.keys())
    mode = "x" if not path.exists() else "a"

    with path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if mode == "x":
            writer.writeheader()
        writer.writerow(row)
