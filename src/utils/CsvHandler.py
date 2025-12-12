import csv
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class ResultColumns:
    inv_usd: float
    strategy: int
    spot_price: float
    k1_price: float
    k2_price: float
    k_poly_price: float
    days_to_expiry: float
    sigma: float
    pm_yes_price: float
    pm_no_price: float
    is_DST: bool
    k1_ask_btc: float
    k1_bid_btc: float
    k2_ask_btc: float
    k2_bid_btc: float

    gross_ev: float
    contract_amount: float
    roi_pct: float

    contracts_amount_final: float

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
    def save_to_result2(csv_path: str,  row_dict: dict[str, str | float]):
        dataclass_fields = list(fields(ResultColumns))
        field_names = [f.name for f in dataclass_fields]

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