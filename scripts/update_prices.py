# update_prices.py
# cron 每個交易日 15:00 執行（SPEC §7.3）。要求：冪等、單檔失敗不中斷整批、記 log。
# 用法：python -m scripts.update_prices
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.db import get_conn, init_db, upsert_sql
from app.services.data_sources.base import get_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("update_prices")


def _symbols_in_use() -> list[str]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT symbol FROM holdings").fetchall()
    finally:
        conn.close()
    return [r["symbol"] for r in rows]


def _latest_date(symbol: str) -> date | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(trade_date) AS d FROM prices WHERE symbol = ?", (symbol,)
        ).fetchone()
    finally:
        conn.close()
    if row and row["d"]:
        return datetime.strptime(row["d"], "%Y-%m-%d").date()
    return None


def update_symbol(symbol: str) -> int:
    """只抓 DB 最新日期之後的資料並 upsert。回傳新增/更新筆數。"""
    source = get_source()
    latest = _latest_date(symbol)
    start = (latest + timedelta(days=1)) if latest else (date.today() - timedelta(days=400))
    end = date.today()
    if start > end:
        return 0
    df = source.get_history(symbol, start, end)
    if df.empty:
        return 0
    conn = get_conn()
    try:
        rows = [(symbol, str(r.trade_date), float(r.close))
                for r in df.itertuples(index=False) if float(r.close) > 0]
        conn.executemany(
            upsert_sql("prices", ["symbol", "trade_date", "close"],
                       ["symbol", "trade_date"], ["close"]),
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main() -> int:
    init_db()
    symbols = _symbols_in_use()
    log.info("本次需更新 %d 檔：%s", len(symbols), symbols)
    ok, failed, missing = 0, 0, []
    for symbol in symbols:
        try:
            n = update_symbol(symbol)
            log.info("更新 %s：%d 筆", symbol, n)
            ok += 1
            if n == 0:
                missing.append(symbol)
        except Exception as exc:  # noqa: BLE001 — 單檔失敗不中斷整批
            log.error("更新 %s 失敗：%s", symbol, exc)
            failed += 1
    log.info("完成。成功 %d、失敗 %d、無新資料 %s", ok, failed, missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
