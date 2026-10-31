# anomaly_service.py
# 偵測掃描與結果讀寫（SPEC-anomaly §9 run_anomaly_scan 的服務化版本）：
#   scan()                    組同業年增率 → 跑引擎 → 交易內重跑 → 寫 anomaly_runs/anomalies + 規則式備援解讀
#   latest_alerts_for()       健檢「基本面提醒」與儀表板徽章用
#   list_anomalies / get_anomaly  雷達頁與詳情頁用
# 數字一律由引擎（純函式）計算，本層只負責資料進出 DB（沿用 D-005 / D-A02）。
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from ..config import settings
from ..db import get_conn, upsert_sql
from . import anomaly_engine as eng
from . import fundamentals_service as fs

# 不跑偵測的產業（ETF 無財報；金融保險業科目結構不同）
SKIP_SECTORS = {"ETF", "金融保險業"}

_MONTHLY_RULES = ("R-REV-YOY",)
_QUARTERLY_RULES = ("R-GM-SHIFT", "R-AR-DIV", "R-INV-DIV", "R-ACCRUAL")

# 寫進 anomaly_runs.params_json，確保結果可重現（答辯時可交代門檻）
_PARAMS = {
    "severity_z": eng.SEVERITY_Z,
    "rev_lookback": eng.REV_LOOKBACK, "rev_min_hist": eng.REV_MIN_HIST,
    "rev_min_abs_dev": eng.REV_MIN_ABS_DEV,
    "q_lookback": eng.Q_LOOKBACK, "q_min_hist": eng.Q_MIN_HIST,
    "gm_min_abs_pp": eng.GM_MIN_ABS_PP, "div_thresholds": eng.DIV_THRESHOLDS,
    "accrual_thresholds": eng.ACCRUAL_THRESHOLDS, "min_peers": eng.MIN_PEERS,
}


# ---------- 共用 ----------
def _sector_map(conn, symbols: list[str]) -> dict[str, str | None]:
    if not symbols:
        return {}
    ph = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"SELECT symbol, sector FROM stocks WHERE symbol IN ({ph})", symbols
    ).fetchall()
    return {r["symbol"]: r["sector"] for r in rows}


def _scan_universe(conn, symbols: list[str] | None) -> tuple[list[str], dict]:
    """決定要掃描的股票集合（排除 ETF / 金融保險業）與其產業對照。"""
    if symbols:
        smap = _sector_map(conn, symbols)
    else:
        rows = conn.execute("SELECT symbol, sector FROM stocks").fetchall()
        smap = {r["symbol"]: r["sector"] for r in rows}
    scan = [s for s, sec in smap.items() if sec not in SKIP_SECTORS]
    return sorted(scan), smap


def period_end_date(period: str) -> date:
    """旗標期間轉成該期末日：'YYYY-MM' → 當月月底；'YYYYQn' → 當季季底。"""
    freq = "Q" if "Q" in period else "M"
    return pd.Period(period, freq=freq).end_time.date()


def _neg_period(period: str) -> int:
    """排序輔助：回傳期末日的負序數，讓升冪排序時「期間新者」排在前面。"""
    return -period_end_date(period).toordinal()


# ---------- 掃描 ----------
def scan(symbols: list[str] | None = None) -> dict:
    """對 symbols（或 stocks 全表）跑月營收與季報偵測；回傳 {'n_flags', 'flags'}。"""
    conn = get_conn()
    try:
        scan_set, smap = _scan_universe(conn, symbols)
        monthly = _run_monthly(conn, scan_set, smap)
        quarterly = _run_quarterly(conn, scan_set)
    finally:
        conn.close()
    flags = monthly + quarterly
    return {"n_flags": len(flags), "flags": flags}


def _run_monthly(conn, scan_set: list[str], smap: dict) -> list[dict]:
    # 先算出每檔的月營收年增率序列，供同業比較共用
    yoy_by_sym: dict[str, pd.Series] = {}
    rev_df_by_sym: dict[str, pd.DataFrame] = {}
    for sym in scan_set:
        df = fs.get_monthly_revenue_df(sym)
        if df.empty:
            continue
        rev_df_by_sym[sym] = df
        yoy = eng.revenue_yoy(df).dropna()
        if not yoy.empty:
            yoy_by_sym[sym] = yoy

    flags: list[dict] = []
    for sym, df in rev_df_by_sym.items():
        yoy = yoy_by_sym.get(sym)
        if yoy is None or yoy.empty:
            continue
        as_of = yoy.index[-1]
        peer_yoy = _peer_yoy_at(sym, as_of, smap, yoy_by_sym)
        flag = eng.detect_revenue_anomaly(sym, df, peer_yoy=peer_yoy)
        if flag:
            flags.append(flag)

    periods = sorted({str(yoy.index[-1]) for yoy in yoy_by_sym.values()})
    _persist(conn, "monthly", _MONTHLY_RULES, scan_set, periods, flags)
    return flags


def _peer_yoy_at(sym: str, as_of: pd.Period, smap: dict,
                 yoy_by_sym: dict[str, pd.Series]) -> pd.Series | None:
    """同產業其他公司在 as_of 月份的年增率（index=symbol），給 detect_revenue_anomaly 用。"""
    sector = smap.get(sym)
    if sector is None:
        return None
    out = {}
    for other, yoy in yoy_by_sym.items():
        if smap.get(other) != sector:
            continue
        if as_of in yoy.index and np.isfinite(yoy[as_of]):
            out[other] = float(yoy[as_of])
    return pd.Series(out, dtype=float) if out else None


def _run_quarterly(conn, scan_set: list[str]) -> list[dict]:
    flags: list[dict] = []
    periods: set[str] = set()
    for sym in scan_set:
        q = fs.get_quarterly_df(sym)
        if q.empty:
            continue
        periods.add(str(q.index.max()))
        flags.extend(eng.detect_quarterly_anomalies(sym, q))
    _persist(conn, "quarterly", _QUARTERLY_RULES, scan_set, sorted(periods), flags)
    return flags


_ANOM_INSERT_COLS = ["run_id", "symbol", "rule_id", "period", "severity",
                     "direction", "value", "baseline", "z", "evidence_json"]
# upsert 衝突時更新的欄位：自然鍵（symbol/rule_id/period）不動，id 因而穩定（D-A17）
_ANOM_UPDATE_COLS = ["run_id", "severity", "direction", "value", "baseline", "z", "evidence_json"]
_ANOM_UPSERT_SQL = upsert_sql("anomalies", _ANOM_INSERT_COLS,
                              ["symbol", "rule_id", "period"], _ANOM_UPDATE_COLS)


def _persist(conn, kind: str, rules: tuple[str, ...], scan_set: list[str],
             periods: list[str], flags: list[dict]) -> None:
    """交易內重跑（以自然鍵 (symbol,rule_id,period) upsert，旗標 id 穩定，不隨每次掃描漂移）：
      1. 刪掉本次掃描範圍內「這次不再出現」的過時旗標（連同其解讀）
      2. 對每個旗標 upsert（已存在則更新數值等欄位，id 不變）
      3. 解讀：無則補規則式備援；原為備援則隨新數值刷新；原為 LLM（RAG）者保留不覆寫
    """
    as_of_period = periods[-1] if periods else ""
    cur = conn.execute(
        "INSERT INTO anomaly_runs (kind, as_of_period, universe_size, params_json, n_flags) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, as_of_period, len(scan_set), json.dumps(_PARAMS, ensure_ascii=False), len(flags)),
    )
    run_id = cur.lastrowid
    new_keys = {(f["symbol"], f["rule_id"], f["period"]) for f in flags}

    if scan_set and periods:
        ph_rule = ",".join("?" * len(rules))
        ph_sym = ",".join("?" * len(scan_set))
        ph_per = ",".join("?" * len(periods))
        existing = conn.execute(
            f"SELECT id, symbol, rule_id, period FROM anomalies WHERE rule_id IN ({ph_rule}) "
            f"AND symbol IN ({ph_sym}) AND period IN ({ph_per})",
            [*rules, *scan_set, *periods],
        ).fetchall()
        stale = [r["id"] for r in existing
                 if (r["symbol"], r["rule_id"], r["period"]) not in new_keys]
        if stale:
            ph = ",".join("?" * len(stale))
            # 顯式刪解讀再刪旗標，不依賴 FK CASCADE（SQLite 預設未開 foreign_keys）
            conn.execute(f"DELETE FROM anomaly_explanations WHERE anomaly_id IN ({ph})", stale)
            conn.execute(f"DELETE FROM anomalies WHERE id IN ({ph})", stale)

    for f in flags:
        conn.execute(_ANOM_UPSERT_SQL, (
            run_id, f["symbol"], f["rule_id"], f["period"], f["severity"], f["direction"],
            f["value"], f["baseline"], f["z"], json.dumps(f["evidence"], ensure_ascii=False)))
        # upsert 後的 lastrowid 跨後端不可靠，用自然鍵查回穩定 id
        anomaly_id = conn.execute(
            "SELECT id FROM anomalies WHERE symbol = ? AND rule_id = ? AND period = ?",
            (f["symbol"], f["rule_id"], f["period"]),
        ).fetchone()["id"]
        ex = conn.execute(
            "SELECT source FROM anomaly_explanations WHERE anomaly_id = ?", (anomaly_id,)
        ).fetchone()
        if ex is None:
            conn.execute(
                "INSERT INTO anomaly_explanations (anomaly_id, explanation, cited_news_ids, source) "
                "VALUES (?, ?, ?, ?)",
                (anomaly_id, eng.fallback_explanation(f), "[]", "fallback"),
            )
        elif ex["source"] == "fallback":
            conn.execute(
                "UPDATE anomaly_explanations SET explanation = ? WHERE anomaly_id = ?",
                (eng.fallback_explanation(f), anomaly_id),
            )
        # source == 'llm'（RAG 解讀）：保留使用者已產生的 AI 解讀，不覆寫
    conn.execute("UPDATE anomaly_runs SET finished_at = ? WHERE id = ?",
                 (_now(), run_id))
    conn.commit()


def _now() -> str:
    return pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 讀取 ----------
def _row_to_alert(r) -> dict:
    ev = json.loads(r["evidence_json"]) if r["evidence_json"] else {}
    return {
        "id": r["id"],
        "symbol": r["symbol"],
        "name": r["name"] if "name" in r.keys() else None,
        "rule_id": r["rule_id"],
        "rule": eng.RULE_NAMES.get(r["rule_id"], r["rule_id"]),
        "period": r["period"],
        "severity": r["severity"],
        "direction": r["direction"],
        "scope": ev.get("scope"),
    }


def latest_alerts_for(symbols: list[str], months: int | None = None) -> list[dict]:
    """每檔持股、每個規則，取最近 `months` 個月內最新一期的旗標（SPEC-anomaly §11）。"""
    if not symbols:
        return []
    months = months or settings.ANOMALY_ALERT_MONTHS
    cutoff = (pd.Timestamp.today() - pd.DateOffset(months=months)).date()
    conn = get_conn()
    try:
        ph = ",".join("?" * len(symbols))
        rows = conn.execute(
            f"SELECT a.*, s.name FROM anomalies a JOIN stocks s ON s.symbol = a.symbol "
            f"WHERE a.symbol IN ({ph}) ORDER BY a.period DESC",
            symbols,
        ).fetchall()
    finally:
        conn.close()

    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        if period_end_date(r["period"]) < cutoff:
            continue
        key = (r["symbol"], r["rule_id"])
        if key not in best:  # rows 已依 period 由新到舊，第一筆即最新
            best[key] = _row_to_alert(r)
    return sorted(best.values(),
                  key=lambda a: (a["symbol"], a["rule_id"]))


def list_anomalies(severity: str | None = None, rule: str | None = None,
                   symbol: str | None = None, limit: int = 100) -> list[dict]:
    """雷達頁列表：預設依嚴重度、期間排序。"""
    sev_rank = {"極端": 0, "顯著": 1, "注意": 2}
    conn = get_conn()
    try:
        sql = ("SELECT a.*, s.name, s.sector FROM anomalies a "
               "JOIN stocks s ON s.symbol = a.symbol WHERE 1=1")
        params: list = []
        if severity:
            sql += " AND a.severity = ?"; params.append(severity)
        if rule:
            sql += " AND a.rule_id = ?"; params.append(rule)
        if symbol:
            sql += " AND a.symbol = ?"; params.append(symbol)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        a = _row_to_alert(r)
        a["sector"] = r["sector"]
        a["z"] = float(r["z"]) if r["z"] is not None else None
        items.append(a)
    # 嚴重度高者在前；同嚴重度內期間新者在前
    items.sort(key=lambda a: (sev_rank.get(a["severity"], 9), _neg_period(a["period"])))
    return items[:limit]


def get_anomaly(anomaly_id: int) -> dict | None:
    """單一旗標詳情：flag、證據、AI/備援解讀、圖表時間序列。"""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT a.*, s.name, s.sector FROM anomalies a "
            "JOIN stocks s ON s.symbol = a.symbol WHERE a.id = ?",
            (anomaly_id,),
        ).fetchone()
        if r is None:
            return None
        ex = conn.execute(
            "SELECT explanation, source, model_name, cited_news_ids "
            "FROM anomaly_explanations WHERE anomaly_id = ?",
            (anomaly_id,),
        ).fetchone()
        cited_ids = json.loads(ex["cited_news_ids"]) if (ex and ex["cited_news_ids"]) else []
        news_by_id = {}
        if cited_ids:
            ph = ",".join("?" * len(cited_ids))
            for nr in conn.execute(
                f"SELECT id, title, link, source, published_at FROM news WHERE id IN ({ph})",
                cited_ids,
            ).fetchall():
                news_by_id[nr["id"]] = {"title": nr["title"], "link": nr["link"],
                                        "source": nr["source"],
                                        "published_at": str(nr["published_at"])[:10]}
    finally:
        conn.close()

    detail = _row_to_alert(r)
    detail["sector"] = r["sector"]
    detail["value"] = float(r["value"]) if r["value"] is not None else None
    detail["baseline"] = float(r["baseline"]) if r["baseline"] is not None else None
    detail["z"] = float(r["z"]) if r["z"] is not None else None
    detail["evidence"] = json.loads(r["evidence_json"]) if r["evidence_json"] else {}
    detail["explanation"] = ex["explanation"] if ex else eng.fallback_explanation({
        **detail, "evidence": detail["evidence"]})
    detail["explanation_source"] = ex["source"] if ex else "fallback"
    # 依 [1..n] 順序回傳被引用的新聞，供前端把 [n] 轉成可點連結（只允許 http/https，§10.3）
    detail["news"] = [
        {"n": i + 1, **news_by_id[nid]}
        for i, nid in enumerate(cited_ids) if nid in news_by_id
        and str(news_by_id[nid]["link"]).startswith(("http://", "https://"))
    ]
    detail["series"] = _series_for(r["symbol"], r["rule_id"])
    return detail


def _series_for(symbol: str, rule_id: str) -> dict:
    """詳情頁折線圖資料：月營收規則回近 36 個月；季報規則回近 12 季的對應指標。"""
    if rule_id == "R-REV-YOY":
        df = fs.get_monthly_revenue_df(symbol)
        if df.empty:
            return {"labels": [], "revenue": [], "yoy": []}
        s = eng.monthly_series(df).tail(36)
        yoy = eng.revenue_yoy(df).reindex(s.index)
        return {
            "labels": [str(p) for p in s.index],
            "revenue": [eng._f(v) for v in s.to_numpy()],
            "yoy": [eng._f(v) for v in yoy.to_numpy()],
        }
    q = fs.get_quarterly_df(symbol)
    if q.empty:
        return {"labels": [], "values": []}
    m = eng.quarterly_metrics(q).tail(12)
    metric_col = {
        "R-GM-SHIFT": "gross_margin", "R-AR-DIV": "ar_div",
        "R-INV-DIV": "inv_div", "R-ACCRUAL": "accruals",
    }.get(rule_id, "rev_yoy")
    return {
        "labels": [str(p) for p in m.index],
        "metric": metric_col,
        "values": [eng._f(v) for v in m[metric_col].to_numpy()],
    }
