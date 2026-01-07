import csv
import logging
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

class CsvHandler:
    @staticmethod
    def check_csv(csv_path: str, expected_columns: list[str], fill_value: Any = "", dtype: dict[str, type] | None = None):
        """
        检查并确保 CSV 文件包含所有期望的列。

        Args:
            csv_path: CSV 文件路径
            expected_columns: 期望的列名列表
            fill_value: 新增列的默认填充值（默认为空字符串）
            dtype: 指定列的数据类型字典（例如 {"yes_token_id": str, "no_token_id": str}）

        Returns:
            bool: 操作是否成功

        功能：
        - 如果文件不存在，创建并写入表头
        - 如果文件存在但缺少列，自动添加缺失的列（填充默认值）
        - 保留现有的额外列（向后兼容）
        """
        path = Path(csv_path)

        # 创建父目录（如果不存在的话）
        path.parent.mkdir(parents=True, exist_ok=True)

        # 检查文件是否存在
        if not path.exists():
            # 文件不存在时，创建文件并写入表头
            with open(path, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(expected_columns)
            logger.info(f"创建新 CSV 文件: {csv_path}，列: {expected_columns}")
            return True

        # 文件存在，检查列是否完整
        try:
            # 读取现有 CSV，使用指定的数据类型（防止大整数被转换为科学计数法）
            df = pd.read_csv(path, dtype=dtype, low_memory=False)
            existing_columns = df.columns.tolist()

            # 找出缺失的列
            missing_columns = [col for col in expected_columns if col not in existing_columns]

            if missing_columns:
                logger.warning(f"CSV 文件 {csv_path} 缺失列: {missing_columns}，自动添加...")

                # 为缺失的列添加默认值
                for col in missing_columns:
                    df[col] = fill_value

                # 重新排列列顺序：保留所有现有列 + 新增列
                # 优先按 expected_columns 顺序，然后是额外的现有列
                all_columns = []
                for col in expected_columns:
                    if col in df.columns:
                        all_columns.append(col)

                # 添加不在 expected_columns 中的额外列
                for col in existing_columns:
                    if col not in all_columns:
                        all_columns.append(col)

                df = df[all_columns]

                # 保存更新后的 CSV（quoting=csv.QUOTE_NONNUMERIC 确保字符串被正确引用）
                df.to_csv(path, index=False, quoting=csv.QUOTE_NONNUMERIC)
                logger.info(f"已为 {csv_path} 添加缺失列: {missing_columns}")

            return True

        except Exception as e:
            logger.error(f"检查 CSV 文件 {csv_path} 时出错: {e}", exc_info=True)
            return False
    
    @staticmethod
    def save_to_csv(csv_path: str,  row_dict: dict[str, str | float], class_obj: Any):
        if not is_dataclass(class_obj):
            raise ValueError("is not dataclass")
        dataclass_fields = list(fields(class_obj))
        field_names = [f.name for f in dataclass_fields]

        # 检查是否有缺失字段
        missing_required = []
        for f in dataclass_fields:
            if f.name not in row_dict:
                missing_required.append(f.name)

        if missing_required:
            raise ValueError(f"缺失必填字段: {missing_required}")

        CsvHandler.check_csv(csv_path, field_names)

        # 组装写入行：按表头顺序输出
        output_row = []
        for f in dataclass_fields:
            val = row_dict[f.name]
            # 确保字符串类型的字段（如 token_id）保持为字符串
            if f.type == str and not isinstance(val, str):
                val = str(val)
            output_row.append(val)

        # 追加写入，使用 QUOTE_NONNUMERIC 确保字符串被正确引用（防止大数字被当作科学计数法）
        path = Path(csv_path)
        with open(path, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerow(output_row)

    @staticmethod
    def delete_csv(csv_path: str, not_exists_ok: bool = False) -> bool:
        """
        删除指定 CSV 文件。
        - 文件存在且删除成功 -> True
        - 文件不存在 -> False
        - 删除失败(权限/占用等) -> False
        """
        path = Path(csv_path)

        if not path.exists():
            return not_exists_ok
        

        try:
            path.unlink()  # 删除文件
            return True
        except (OSError, PermissionError):
            return False