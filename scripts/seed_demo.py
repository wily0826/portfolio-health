# seed_demo.py — 建立三組展示持股（SPEC §9.4 / T-21）
# 集中型 / 分散型 / ETF 型，各建一個 demo 帳號，方便答辯時快速切換展示。
# 另外回補整個展示股池的合成財報並跑一次財報變動偵測，讓「基本面提醒」與雷達頁有內容
# （SPEC-anomaly 展示切片）。
# 用法：python -m scripts.seed_demo
from __future__ import annotations

from app.auth import hash_password
from app.db import get_conn, init_db, upsert_sql
from app.services import anomaly_service, fundamentals_service
from app.services.data_sources.synthetic import catalog_symbols
from scripts.backfill import backfill_symbol, ensure_stock

DEMO_PASSWORD = "demo1234"

PORTFOLIOS = {
    "demo-concentrated@example.com": {
        "name": "展示-集中型",
        "holdings": [("2330.TW", 2000), ("2454.TW", 300), ("3711.TW", 500)],  # 幾乎全半導體
    },
    "demo-diversified@example.com": {
        "name": "展示-分散型",
        "holdings": [("2330.TW", 200), ("2412.TW", 2000), ("2881.TW", 3000),
                     ("1216.TW", 2000), ("2002.TW", 3000), ("2603.TW", 1000)],
    },
    "demo-etf@example.com": {
        "name": "展示-ETF型",
        "holdings": [("0050.TW", 1000), ("0056.TW", 2000), ("2330.TW", 300)],
    },
}


def _create_user(conn, email: str, name: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, display_name) VALUES (?, ?, ?)",
        (email, hash_password(DEMO_PASSWORD), name),
    )
    conn.commit()
    return cur.lastrowid


def main() -> int:
    init_db()
    # 持股會用到的股票：要有股價（健檢）也要有財報（基本面提醒）
    held_symbols = {s for p in PORTFOLIOS.values() for s, _ in p["holdings"]}
    # 展示股池：含同業比較需要的其他半導體等，只需基本資料 + 財報（不需股價）
    universe = sorted(set(catalog_symbols()) | held_symbols)

    print("回補股票基本資料與財報…")
    for sym in universe:
        try:
            ensure_stock(sym)
        except LookupError:
            print(f"  [SKIP] {sym}：查無基本資料"); continue
        if sym in held_symbols:
            n = backfill_symbol(sym)  # 股價（健檢用）
            print(f"  {sym}：股價 {n} 筆", end="")
        else:
            print(f"  {sym}：", end="")
        fin = fundamentals_service.backfill_symbol(sym)  # 財報（偵測用）
        print(f"，財報 月營收 {fin['revenue']} 筆 / 報表 {fin['items']} 筆")

    print("\n跑財報變動偵測…")
    scan = anomaly_service.scan()
    print(f"  共偵測到 {scan['n_flags']} 個財報變動旗標")

    conn = get_conn()
    try:
        for email, p in PORTFOLIOS.items():
            uid = _create_user(conn, email, p["name"])
            for sym, shares in p["holdings"]:
                conn.execute(
                    upsert_sql("holdings", ["user_id", "symbol", "shares"],
                               ["user_id", "symbol"], ["shares"]),
                    (uid, sym, shares),
                )
            conn.commit()
            print(f"[OK] {p['name']}（{email} / {DEMO_PASSWORD}）：{len(p['holdings'])} 檔")
    finally:
        conn.close()
    print("\n完成。可用上述任一帳號登入展示三種風險特徵。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
