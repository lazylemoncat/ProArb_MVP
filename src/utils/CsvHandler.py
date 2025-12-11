import csv
from pathlib import Path

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