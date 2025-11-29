from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _read_existing_header(path: Path) -> List[str]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    return [h for h in header if h]


def ensure_csv_file(csv_path: str, header: Iterable[str] | None = None) -> None:
    """
    Ensure the parent directory exists and the csv file is present.

    If ``header`` is provided and the file did not exist, write that header.
    Otherwise, just touch the file so downstream readers don't fail on missing
    paths.
    """

    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        return

    if header:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(header))
            writer.writeheader()
    else:
        path.touch()


def save_result_csv(row: Dict[str, Any], csv_path: str = "data/results.csv") -> None:
    """
    保存结果到 CSV 文件。
    - 如果文件不存在：写入表头 + 首行
    - 如果文件已存在：确保表头包含本次 row 的全部列；如发现新列则自动升级表头并重写文件

    Args:
        row: 待保存的单行数据（key 为列名）
        csv_path: 输出的 csv 文件路径
    """
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        header = list(row.keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)
        return

    existing_header = _read_existing_header(path)
    # 兼容旧文件：如果文件存在但没有 header（异常情况）
    if not existing_header:
        existing_header = list(row.keys())

    # 合并 header（保持旧顺序，新增字段追加到末尾）
    new_header = list(existing_header)
    for k in row.keys():
        if k not in new_header:
            new_header.append(k)

    if new_header != existing_header:
        # 需要升级 header：读出旧数据，重写一个包含新 header 的文件
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)

        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=new_header)
            writer.writeheader()
            for r in existing_rows:
                writer.writerow(r)
            writer.writerow(row)

        tmp_path.replace(path)
        return

    # header 不变：直接追加
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=existing_header)
        writer.writerow(row)
