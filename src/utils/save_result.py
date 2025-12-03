import csv
import os
import threading  # 导入线程锁
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

# 使用锁来确保文件写入时互斥
file_lock = threading.Lock()

@dataclass(frozen=True)
class ResultsCsvHeader:
    """Canonical results.csv columns kept as a dataclass for easy edits and comments."""
    timestamp: str = "timestamp"
    market_title: str = "market_title"
    asset: str = "asset"
    investment: str = "investment"
    selected_strategy: str = "selected_strategy"
    market_id: str = "market_id"
    pm_event_title: str = "pm_event_title"
    pm_market_title: str = "pm_market_title"
    pm_event_id: str = "pm_event_id"
    pm_market_id: str = "pm_market_id"
    yes_token_id: str = "yes_token_id"
    no_token_id: str = "no_token_id"
    inst_k1: str = "inst_k1"
    inst_k2: str = "inst_k2"
    spot: str = "spot"
    poly_yes_price: str = "poly_yes_price"
    poly_no_price: str = "poly_no_price"
    deribit_prob: str = "deribit_prob"
    K1: str = "K1"
    K2: str = "K2"
    K_poly: str = "K_poly"
    T: str = "T"
    days_to_expiry: str = "days_to_expiry"
    sigma: str = "sigma"
    r: str = "r"
    k1_bid_btc: str = "k1_bid_btc"
    k1_ask_btc: str = "k1_ask_btc"
    k2_bid_btc: str = "k2_bid_btc"
    k2_ask_btc: str = "k2_ask_btc"
    k1_iv: str = "k1_iv"
    k2_iv: str = "k2_iv"
    net_ev_strategy1: str = "net_ev_strategy1"
    gross_ev_strategy1: str = "gross_ev_strategy1"
    total_cost_strategy1: str = "total_cost_strategy1"
    open_cost_strategy1: str = "open_cost_strategy1"
    holding_cost_strategy1: str = "holding_cost_strategy1"
    close_cost_strategy1: str = "close_cost_strategy1"
    contracts_strategy1: str = "contracts_strategy1"
    im_usd_strategy1: str = "im_usd_strategy1"
    im_btc_strategy1: str = "im_btc_strategy1"
    net_ev_strategy2: str = "net_ev_strategy2"
    gross_ev_strategy2: str = "gross_ev_strategy2"
    total_cost_strategy2: str = "total_cost_strategy2"
    open_cost_strategy2: str = "open_cost_strategy2"
    holding_cost_strategy2: str = "holding_cost_strategy2"
    close_cost_strategy2: str = "close_cost_strategy2"
    contracts_strategy2: str = "contracts_strategy2"
    im_usd_strategy2: str = "im_usd_strategy2"
    im_btc_strategy2: str = "im_btc_strategy2"
    avg_price_open_strategy1: str = "avg_price_open_strategy1"
    avg_price_close_strategy1: str = "avg_price_close_strategy1"
    shares_strategy1: str = "shares_strategy1"
    avg_price_open_strategy2: str = "avg_price_open_strategy2"
    avg_price_close_strategy2: str = "avg_price_close_strategy2"
    shares_strategy2: str = "shares_strategy2"
    slippage_open_strategy1: str = "slippage_open_strategy1"
    slippage_open_strategy2: str = "slippage_open_strategy2"

    def as_list(self) -> List[str]:
        return [
            self.timestamp,
            self.market_title,
            self.asset,
            self.investment,
            self.selected_strategy,
            self.market_id,
            self.pm_event_title,
            self.pm_market_title,
            self.pm_event_id,
            self.pm_market_id,
            self.yes_token_id,
            self.no_token_id,
            self.inst_k1,
            self.inst_k2,
            self.spot,
            self.poly_yes_price,
            self.poly_no_price,
            self.deribit_prob,
            self.K1,
            self.K2,
            self.K_poly,
            self.T,
            self.days_to_expiry,
            self.sigma,
            self.r,
            self.k1_bid_btc,
            self.k1_ask_btc,
            self.k2_bid_btc,
            self.k2_ask_btc,
            self.k1_iv,
            self.k2_iv,
            self.net_ev_strategy1,
            self.gross_ev_strategy1,
            self.total_cost_strategy1,
            self.open_cost_strategy1,
            self.holding_cost_strategy1,
            self.close_cost_strategy1,
            self.contracts_strategy1,
            self.im_usd_strategy1,
            self.im_btc_strategy1,
            self.net_ev_strategy2,
            self.gross_ev_strategy2,
            self.total_cost_strategy2,
            self.open_cost_strategy2,
            self.holding_cost_strategy2,
            self.close_cost_strategy2,
            self.contracts_strategy2,
            self.im_usd_strategy2,
            self.im_btc_strategy2,
            self.avg_price_open_strategy1,
            self.avg_price_close_strategy1,
            self.shares_strategy1,
            self.avg_price_open_strategy2,
            self.avg_price_close_strategy2,
            self.shares_strategy2,
            self.slippage_open_strategy1,
            self.slippage_open_strategy2,
        ]


RESULTS_CSV_HEADER = ResultsCsvHeader()

POSITIONS_CSV_HEADER = [
    # 基础信息
    "trade_id",
    "market_id",
    "direction",           # "yes" 或 "no"
    "strategy",            # 策略编号 (1 或 2)
    "status",              # "OPEN", "DRY_RUN", "CLOSED", "EXITED"
    "entry_timestamp",

    # PM 头寸信息
    "pm_token_id",         # YES/NO token ID，用于执行卖单
    "pm_tokens",           # 持有的 token 数量
    "pm_entry_cost",       # PM 端投入成本（USDC）
    "entry_price_pm",      # PM 入场均价

    # DR 头寸信息
    "contracts",           # Deribit 合约数量
    "dr_entry_cost",       # DR 端入场成本（可为负=净收入）
    "inst_k1",             # Deribit K1 合约名
    "inst_k2",             # Deribit K2 合约名

    # 行权价信息
    "K_poly",              # Polymarket 边界价格
    "K1",                  # 下行权价
    "K2",                  # 上行权价

    # 资本信息
    "im_usd",              # 保证金（USD）
    "capital_input",       # 总资本占用

    # 到期信息
    "expiry_date",         # 到期日 (YYYY-MM-DD)
    "expiry_timestamp",    # 到期时间戳（毫秒）

    # 平仓信息（平仓后填充）
    "exit_timestamp",      # 平仓时间
    "exit_price_pm",       # PM 平仓均价
    "settlement_price",    # DR 结算价
    "exit_pnl",            # 平仓盈亏
    "exit_reason",         # "early_exit", "expired", "manual"
]


def _normalize_header(header: Iterable[str] | ResultsCsvHeader | None) -> List[str]:
    if header is None:
        return []
    if isinstance(header, ResultsCsvHeader):
        return header.as_list()
    return list(header)


def _read_existing_header(path: Path) -> List[str]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    return [h for h in header if h]


def ensure_csv_file(
    csv_path: str, header: Iterable[str] | ResultsCsvHeader | None = None
) -> None:
    """
    Ensure the parent directory exists and the csv file is present.

    If ``header`` is provided and the file did not exist, write that header.
    Otherwise, just touch the file so downstream readers don't fail on missing
    paths.
    """

    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized_header: Sequence[str] = _normalize_header(header)

    if path.exists():
        if normalized_header and path.stat().st_size == 0:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(normalized_header))
                writer.writeheader()
        return

    if normalized_header:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(normalized_header))
            writer.writeheader()
    else:
        path.touch()


def rewrite_csv_with_header(
    csv_path: str, header: Iterable[str] | ResultsCsvHeader
) -> None:
    """Rewrite an existing CSV to match the provided header while preserving rows.

    - Missing columns are added with empty values.
    - Extra columns in existing rows are dropped.
    - The operation is guarded by the module-level file lock to avoid races.
    """

    normalized_header = _normalize_header(header)
    path = Path(csv_path)

    with file_lock:
        ensure_csv_file(csv_path, header=normalized_header)

        try:
            with path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing_rows = list(reader)
        except FileNotFoundError:
            existing_rows = []

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(normalized_header))
            writer.writeheader()
            for row in existing_rows:
                writer.writerow({key: row.get(key) for key in normalized_header})
            f.flush()
            os.fsync(f.fileno())


def save_position_to_csv(row: Dict[str, Any], csv_path: str = "data/positions.csv") -> None:
    """Append a single position row to ``positions.csv`` with a stable header."""
    ensure_csv_file(csv_path, header=POSITIONS_CSV_HEADER)

    # Restrict to the known header fields to avoid accidental schema drift.
    filtered_row = {key: row.get(key) for key in POSITIONS_CSV_HEADER}

    with Path(csv_path).open("a", newline="", encoding="utf-8") as f:
        # 使用线程锁来确保文件写入时不会并发
        with file_lock:
            writer = csv.DictWriter(f, fieldnames=list(POSITIONS_CSV_HEADER))
            writer.writerow(filtered_row)


def save_result_csv(row: Dict[str, Any], csv_path: str = "data/results.csv") -> None:
    """
    保存结果到 CSV 文件。
    - 如果文件不存在：写入表头 + 首行
    - 如果文件已存在：确保表头包含本次 row 的全部列；如发现新列则自动升级表头并重写文件

    使用模块级线程锁包裹整个读写流程，避免并发写入导致文件被截断或数据丢失。
    """
    path = Path(csv_path)

    # 使用线程锁来确保文件写入时不会并发
    with file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            header = list(row.keys())
            with path.open("w+", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                writer.writeheader()
                writer.writerow(row)
                f.flush()
                os.fsync(f.fileno())
            return

        with path.open("r+", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_header = [h for h in next(reader, []) if h]
            if not existing_header:
                existing_header = list(row.keys())

            new_header = list(existing_header)
            for k in row.keys():
                if k not in new_header:
                    new_header.append(k)

            if new_header != existing_header:
                f.seek(0)
                existing_rows = list(csv.DictReader(f))

                tmp_path = path.with_suffix(".tmp")
                with tmp_path.open("w", newline="", encoding="utf-8") as tmp_f:
                    writer = csv.DictWriter(tmp_f, fieldnames=new_header)
                    writer.writeheader()
                    for r in existing_rows:
                        writer.writerow(r)
                    writer.writerow(row)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())

                tmp_path.replace(path)
                return

            f.seek(0, os.SEEK_END)
            writer = csv.DictWriter(f, fieldnames=existing_header)
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())
