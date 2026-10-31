# price_service.py
# 從 DB 取價格、整理日期、處理缺值（流程強化版 §3.3）。
# MVP 僅台股，價格已是 TWD，不需匯率換算（§4.3-6）。
from __future__ import annotations

import pandas as pd

from ..db import get_conn
from .risk_engine import MIN_OBS

# 資料狀態（流程強化版 Step4）
STATUS_READY = "ready"
STATUS_LOADING = "loading"
STATUS_INSUFFICIENT = "insufficient"
STATUS_ERROR = "error"


def get_prices_df(symbols: list[str]) -> pd.DataFrame:
    """從 prices 表組出 index=日期、columns=symbol 的還原價 DataFrame。"""
    if not symbols:
        return pd.DataFrame()
    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(symbols))
        rows = conn.execute(
            f"SELECT symbol, trade_date, close FROM prices "
            f"WHERE symbol IN ({placeholders}) ORDER BY trade_date",
            symbols,
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    # MySQL 的 DECIMAL 會回傳 decimal.Decimal，統一轉 float，避免風險引擎 Decimal×float 錯誤
    df["close"] = df["close"].astype(float)
    wide = df.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    return wide


def get_sector_map(symbols: list[str]) -> dict[str, str | None]:
    if not symbols:
        return {}
    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(symbols))
        rows = conn.execute(
            f"SELECT symbol, sector FROM stocks WHERE symbol IN ({placeholders})",
            symbols,
        ).fetchall()
    finally:
        conn.close()
    return {r["symbol"]: r["sector"] for r in rows}


def symbol_status(symbol: str) -> str:
    """單一 symbol 的資料狀態（給前端顯示用）。"""
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM prices WHERE symbol = ?", (symbol,)
        ).fetchone()["c"]
    finally:
        conn.close()
    if n == 0:
        return STATUS_LOADING
    if n < MIN_OBS:
        return STATUS_INSUFFICIENT
    return STATUS_READY
