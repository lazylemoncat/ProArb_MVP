from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List


def _read_existing_header(path: Path) -> List[str] | None:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            return header or None
    except FileNotFoundError:
        return None


def _rewrite_with_merged_header(path: Path, merged_header: List[str]) -> None:
    # 读取旧数据
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_header, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in merged_header}
            writer.writerow(out)

    tmp_path.replace(path)


def save_result_csv(row: Dict[str, Any], csv_path: str = "data/results.csv") -> None:
    """
    保存结果到 CSV 文件：
    - 如果文件不存在则写入表头；
    - 如果文件已存在但“字段列表变化”，会自动合并表头并重写旧文件（保证 API 读起来不乱列）。

    Args:
        row: 待保存的单行数据（key 为列名）
        csv_path: 输出的 csv 文件路径
    """
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    new_header = list(row.keys())
    old_header = _read_existing_header(path)

    if old_header is None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=new_header)
            writer.writeheader()
            writer.writerow(row)
        return

    if old_header != new_header:
        merged = list(old_header)
        for k in new_header:
            if k not in merged:
                merged.append(k)
        _rewrite_with_merged_header(path, merged)
        header = merged
    else:
        header = old_header

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writerow({k: row.get(k, "") for k in header})
