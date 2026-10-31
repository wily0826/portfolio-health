# fundamentals_service.py
# 財報資料層（SPEC-anomaly §5.4 / §15）：
#   - backfill_symbol：資料來源 → DB（fin_month_revenue / fin_statement_items），比照股價的回補流程
#   - get_monthly_revenue_df / get_quarterly_df：DB → 偵測引擎需要的 DataFrame
# 引擎只認得標準欄位名，科目對照已在資料來源端完成；本層負責把 CF 的累計數轉單季。
from __future__ import annotations

import pandas as pd

from ..db import get_conn, upsert_sql
from .anomaly_engine import QUARTER_COLUMNS, decumulate_ytd
from .data_sources.fundamentals_base import get_fundamentals_source


def backfill_symbol(symbol: str) -> dict:
    """抓取並 upsert 單一股票的月營收與三大報表（冪等）。回傳寫入筆數。"""
    source = get_fundamentals_source()
    rev_rows = source.get_monthly_revenue(symbol)
    item_rows = source.get_statement_items(symbol)

    conn = get_conn()
    try:
        if rev_rows:
            conn.executemany(
                upsert_sql("fin_month_revenue",
                           ["symbol", "revenue_year", "revenue_month", "revenue"],
                           ["symbol", "revenue_year", "revenue_month"], ["revenue"]),
                [(symbol, r["revenue_year"], r["revenue_month"], r["revenue"]) for r in rev_rows],
            )
        if item_rows:
            conn.executemany(
                upsert_sql("fin_statement_items",
                           ["symbol", "period_end", "statement", "item_type", "origin_name", "value"],
                           ["symbol", "period_end", "statement", "item_type"],
                           ["origin_name", "value"]),
                [(symbol, r["period_end"], r["statement"], r["item_type"],
                  r["origin_name"], r["value"]) for r in item_rows],
            )
        conn.commit()
    finally:
        conn.close()
    return {"revenue": len(rev_rows), "items": len(item_rows)}


def get_monthly_revenue_df(symbol: str) -> pd.DataFrame:
    """從 DB 組出月營收 DataFrame（欄位 revenue_year, revenue_month, revenue）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT revenue_year, revenue_month, revenue FROM fin_month_revenue "
            "WHERE symbol = ? ORDER BY revenue_year, revenue_month",
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(columns=["revenue_year", "revenue_month", "revenue"])
    df = pd.DataFrame(rows, columns=["revenue_year", "revenue_month", "revenue"])
    df["revenue"] = df["revenue"].astype(float)
    return df


def get_quarterly_df(symbol: str) -> pd.DataFrame:
    """從 DB 組出季報寬表：index 為季 Period、欄位為引擎標準欄位名；cfo 已轉單季。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT period_end, statement, item_type, value FROM fin_statement_items "
            "WHERE symbol = ? ORDER BY period_end",
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(columns=QUARTER_COLUMNS)

    df = pd.DataFrame(rows, columns=["period_end", "statement", "item_type", "value"])
    df["value"] = df["value"].astype(float)
    df["q"] = pd.PeriodIndex(pd.to_datetime(df["period_end"]), freq="Q")

    # 非現金流科目（IS 單季、BS 時點數）：直接攤成寬表
    non_cf = df[df["statement"] != "CF"]
    wide = non_cf.pivot_table(index="q", columns="item_type", values="value", aggfunc="last")

    # 現金流：DB 存累計數（YTD）→ 轉單季（SPEC-anomaly §6.7）
    cf = df[df["statement"] == "CF"]
    if not cf.empty:
        cfo_ytd = pd.Series(cf["value"].to_numpy(),
                            index=pd.to_datetime(cf["period_end"]))
        wide = wide.reindex(wide.index.union(pd.PeriodIndex(cfo_ytd.index, freq="Q")))
        wide["cfo"] = decumulate_ytd(cfo_ytd)

    wide = wide.sort_index()
    for c in QUARTER_COLUMNS:
        if c not in wide.columns:
            wide[c] = float("nan")
    return wide[QUARTER_COLUMNS]
