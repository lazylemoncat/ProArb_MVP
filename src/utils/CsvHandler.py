import csv
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

class CsvHandler:
    @staticmethod
    def check_csv(csv_path: str, expected_columns: list[str]):
        path = Path(csv_path)
        
        # 创建父目录（如果不存在的话）
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 检查文件是否存在
        if not path.exists():
            # 文件不存在时，创建文件并写入表头
            with open(path, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(expected_columns)
        # 如果文件已存在，什么也不做
        return True
    
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
            output_row.append(val)

        # 追加写入
        path = Path(csv_path)
        with open(path, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
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