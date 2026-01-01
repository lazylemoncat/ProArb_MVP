import json
from dataclasses import asdict
from datetime import timezone
from typing import Any, Dict, Tuple

import mysql.connector
from .save_result2 import SaveResult
from ..fetch_data.polymarket.polymarket_client import PolymarketContext
from ..fetch_data.deribit.deribit_client import DeribitMarketContext

# 这些字段在 dataclass 里是 list/tuple，建议在 MySQL 表中用 JSON 类型存
_JSON_FIELDS = {
    "spot_iv_lower",
    "spot_iv_upper",
    "k1_ask_1_usd", "k1_ask_2_usd", "k1_ask_3_usd",
    "k2_ask_1_usd", "k2_ask_2_usd", "k2_ask_3_usd",
    "k1_bid_1_usd", "k1_bid_2_usd", "k1_bid_3_usd",
    "k2_bid_1_usd", "k2_bid_2_usd", "k2_bid_3_usd",
}


def _normalize_datetime(dt):
    """MySQL DATETIME 不存时区；如果是 aware datetime，则转成 UTC naive。"""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _prepare_row_for_mysql(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 list/tuple 转成 JSON 字符串，datetime 做必要归一化。"""
    row = dict(row)  # copy

    # datetime
    if "time" in row:
        row["time"] = _normalize_datetime(row["time"])

    # JSON fields
    for k in _JSON_FIELDS:
        if k in row and row[k] is not None:
            row[k] = json.dumps(row[k], ensure_ascii=False, separators=(",", ":"))

    return row


def save_result_to_mysql(
    pm_ctx: PolymarketContext,  # PolymarketContext
    db_ctx: DeribitMarketContext,  # DeribitMarketContext
    mysql_cfg: Dict[str, Any],
    table: str = "raw_results",
) -> Tuple["SaveResult", int]:
    """
    将 SaveResult 写入 MySQL: proarb.raw_results
    mysql_cfg 示例：
      {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": "root",
        "database": "proarb",
      }
    返回：(row_obj, inserted_id)
    """
    # 1) 组装 dataclass（与你现有逻辑一致）
    row_obj = SaveResult(
        time=pm_ctx.time,
        event_title=pm_ctx.event_title,
        market_title=pm_ctx.market_title,
        event_id=pm_ctx.event_id,
        market_id=pm_ctx.market_id,
        yes_price=pm_ctx.yes_price,
        no_price=pm_ctx.no_price,

        yes_token_id=pm_ctx.yes_token_id,
        no_token_id=pm_ctx.no_token_id,

        yes_bid_price_1=pm_ctx.yes_bid_price_1,
        yes_bid_price_size_1=pm_ctx.yes_bid_price_size_1,
        yes_bid_price_2=pm_ctx.yes_bid_price_2,
        yes_bid_price_size_2=pm_ctx.yes_bid_price_size_2,
        yes_bid_price_3=pm_ctx.yes_bid_price_3,
        yes_bid_price_size_3=pm_ctx.yes_bid_price_size_3,

        yes_ask_price_1=pm_ctx.yes_ask_price_1,
        yes_ask_price_1_size=pm_ctx.yes_ask_price_1_size,
        yes_ask_price_2=pm_ctx.yes_ask_price_2,
        yes_ask_price_2_size=pm_ctx.yes_ask_price_2_size,
        yes_ask_price_3=pm_ctx.yes_ask_price_3,
        yes_ask_price_3_size=pm_ctx.yes_ask_price_3_size,

        no_bid_price_1=pm_ctx.no_bid_price_1,
        no_bid_price_size_1=pm_ctx.no_bid_price_size_1,
        no_bid_price_2=pm_ctx.no_bid_price_2,
        no_bid_price_size_2=pm_ctx.no_bid_price_size_2,
        no_bid_price_3=pm_ctx.no_bid_price_3,
        no_bid_price_size_3=pm_ctx.no_bid_price_size_3,

        no_ask_price_1=pm_ctx.no_ask_price_1,
        no_ask_price_1_size=pm_ctx.no_ask_price_1_size,
        no_ask_price_2=pm_ctx.no_ask_price_2,
        no_ask_price_2_size=pm_ctx.no_ask_price_2_size,
        no_ask_price_3=pm_ctx.no_ask_price_3,
        no_ask_price_3_size=pm_ctx.no_ask_price_3_size,

        asset=db_ctx.asset,
        spot=db_ctx.spot,
        inst_k1=db_ctx.inst_k1,
        inst_k2=db_ctx.inst_k2,
        k1_strike=db_ctx.k1_strike,
        k2_strike=db_ctx.k2_strike,
        K_poly=db_ctx.K_poly,

        k1_bid_btc=db_ctx.k1_bid_btc,
        k1_ask_btc=db_ctx.k1_ask_btc,
        k2_bid_btc=db_ctx.k2_bid_btc,
        k2_ask_btc=db_ctx.k2_ask_btc,
        k1_mid_btc=db_ctx.k1_mid_btc,
        k2_mid_btc=db_ctx.k2_mid_btc,

        k1_bid_usd=db_ctx.k1_bid_usd,
        k1_ask_usd=db_ctx.k1_ask_usd,
        k2_bid_usd=db_ctx.k2_bid_usd,
        k2_ask_usd=db_ctx.k2_ask_usd,
        k1_mid_usd=db_ctx.k1_mid_usd,
        k2_mid_usd=db_ctx.k2_mid_usd,

        k1_iv=db_ctx.k1_iv,
        k2_iv=db_ctx.k2_iv,
        spot_iv_lower=db_ctx.spot_iv_lower,
        spot_iv_upper=db_ctx.spot_iv_upper,
        k1_fee_approx=db_ctx.k1_fee_approx,
        k2_fee_approx=db_ctx.k2_fee_approx,
        mark_iv=db_ctx.mark_iv,

        k1_expiration_timestamp=db_ctx.k1_expiration_timestamp,
        T=db_ctx.T,
        days_to_expairy=db_ctx.days_to_expairy,
        r=db_ctx.r,
        deribit_prob=db_ctx.deribit_prob,

        k1_ask_1_usd=db_ctx.k1_ask_1_usd,
        k1_ask_2_usd=db_ctx.k1_ask_2_usd,
        k1_ask_3_usd=db_ctx.k1_ask_3_usd,
        k2_ask_1_usd=db_ctx.k2_ask_1_usd,
        k2_ask_2_usd=db_ctx.k2_ask_2_usd,
        k2_ask_3_usd=db_ctx.k2_ask_3_usd,

        k1_bid_1_usd=db_ctx.k1_bid_1_usd,
        k1_bid_2_usd=db_ctx.k1_bid_2_usd,
        k1_bid_3_usd=db_ctx.k1_bid_3_usd,
        k2_bid_1_usd=db_ctx.k2_bid_1_usd,
        k2_bid_2_usd=db_ctx.k2_bid_2_usd,
        k2_bid_3_usd=db_ctx.k2_bid_3_usd,
    )

    # 2) 准备 row dict（list/tuple -> JSON；datetime 归一化）
    row = _prepare_row_for_mysql(asdict(row_obj))

    # 3) 生成 INSERT SQL（列名全部加反引号，避免关键字冲突）
    cols = list(row.keys())
    col_sql = ", ".join(f"`{c}`" for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})"

    values = [row[c] for c in cols]

    # 4) 写入数据库
    conn = mysql.connector.connect(**mysql_cfg)
    try:
        cur = conn.cursor()
        cur.execute(sql, values)
        conn.commit()
        inserted_id = cur.lastrowid
        cur.close()
        return row_obj, inserted_id
    finally:
        conn.close()
