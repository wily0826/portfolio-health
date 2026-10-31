# backfill.py
# 新增股票時回補歷史價（SPEC §7.3）。可被 API 與 CLI 共用。
# 用法（CLI）：python -m scripts.backfill 2330.TW
from __future__ import annotations

import sys
from datetime import date, timedelta

from app.config import settings
from app.db import get_conn, init_db, upsert_sql
from app.services.data_sources.base import get_source


def ensure_stock(symbol: str) -> dict:
    """確認 stocks 有此股票；沒有就向資料來源查基本資料並建檔。回傳股票資訊。
    查無此股票時拋 LookupError。"""
    source = get_source()
    info = source.get_info(symbol)  # 查無會拋 LookupError
    conn = get_conn()
    try:
        conn.execute(
            upsert_sql("stocks", ["symbol", "market", "name", "sector", "currency"],
                       ["symbol"], ["name", "sector", "currency"]),
            (symbol, info["market"], info["name"], info.get("sector"), info["currency"]),
        )
        conn.commit()
    finally:
        conn.close()
    return info


def backfill_symbol(symbol: str, years: int | None = None) -> int:
    """抓過去 years 年的還原價寫入 prices（冪等 upsert）。回傳寫入筆數。"""
    years = years or settings.BACKFILL_YEARS
    end = date.today()
    start = end - timedelta(days=365 * years + 10)
    source = get_source()
    df = source.get_history(symbol, start, end)
    if df.empty:
        return 0
    conn = get_conn()
    try:
        rows = [
            (symbol, str(r.trade_date), float(r.close))
            for r in df.itertuples(index=False)
            if float(r.close) > 0  # 價格必須大於 0（流程強化版 §4.3-5）
        ]
        conn.executemany(
            upsert_sql("prices", ["symbol", "trade_date", "close"],
                       ["symbol", "trade_date"], ["close"]),
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main(argv: list[str]) -> int:
    if not argv:
        print("用法：python -m scripts.backfill <symbol> [更多 symbol ...]")
        return 1
    init_db()
    for symbol in argv:
        symbol = symbol.strip().upper()
        try:
            info = ensure_stock(symbol)
            n = backfill_symbol(symbol)
            print(f"[OK] {symbol} {info['name']}（{info.get('sector')}）回補 {n} 筆")
        except LookupError:
            print(f"[SKIP] {symbol}：查無此股票")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {symbol}：{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
