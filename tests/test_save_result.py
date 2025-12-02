import csv
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.save_result import RESULTS_CSV_HEADER, rewrite_csv_with_header, save_result_csv


def test_save_result_csv_appends_rows(tmp_path):
    csv_path = tmp_path / "results.csv"

    rows = [
        {"timestamp": "2024-01-01 00:00:00", "market_title": "m1"},
        {"timestamp": "2024-01-01 00:00:01", "market_title": "m2", "extra": "x"},
    ]

    for row in rows:
        save_result_csv(row, csv_path=str(csv_path))

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        saved = list(reader)

    assert len(saved) == len(rows)
    assert saved[-1]["extra"] == "x"


def test_save_result_csv_thread_safety(tmp_path):
    csv_path = tmp_path / "results.csv"

    def _writer(idx: int) -> None:
        save_result_csv(
            {
                "timestamp": f"2024-01-01 00:00:{idx:02d}",
                "market_title": f"m{idx}",
                "value": idx,
            },
            csv_path=str(csv_path),
        )

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        saved = list(reader)

    assert len(saved) == 5
    assert {row["market_title"] for row in saved} == {f"m{i}" for i in range(5)}


def test_rewrite_preserves_rows(tmp_path):
    csv_path = tmp_path / "results.csv"

    legacy_header = ["timestamp", "market_title", "asset"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=legacy_header)
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2024-01-01 00:00:00",
                "market_title": "old",
                "asset": "BTC",
            }
        )

    rewrite_csv_with_header(str(csv_path), RESULTS_CSV_HEADER)

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["market_title"] == "old"
