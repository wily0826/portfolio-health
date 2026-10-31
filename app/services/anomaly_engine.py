# anomaly_engine.py
"""財報異常偵測引擎：純函式，不碰 DB、不碰網路（SPEC-anomaly §7.1）。"""
from __future__ import annotations

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

# ---------- 參數（改這裡要同步改 SPEC-anomaly.md §6） ----------
MAD_SCALE = 1.4826          # MAD → 標準差的換算係數（常態分布下）
MEANAD_SCALE = 1.2533       # MAD = 0 時改用平均絕對偏差的換算係數
SEVERITY_Z = [(8.0, "極端"), (5.0, "顯著"), (3.5, "注意")]

REV_LOOKBACK = 24           # 營收：拿過去幾個月的年增率當基準
REV_MIN_HIST = 12           # 營收：基準至少要幾個月
REV_MIN_ABS_DEV = 0.20      # 營收：年增率至少偏離基準中位數 20 個百分點才算（重大性門檻）
MIN_BASE_REVENUE = 1.0      # 去年同期營收 <= 此值不算成長率（避免基期趨近 0）

Q_LOOKBACK = 12             # 季報：基準季數
Q_MIN_HIST = 8              # 季報：基準至少季數
GM_MIN_ABS_PP = 4.0         # 毛利率：至少偏離 4 個百分點才算（A-11 校準：3pp 對傳產毛利率季波動太敏感，D-A19）
GM_NOTE_MIN_Z = 4.0         # 毛利率「注意」級單獨拉高 z 門檻（傳產季波動大，3.5 剛過線多為雜訊，A-11，D-A20）
DIV_THRESHOLDS = [(0.60, "顯著"), (0.30, "注意")]       # 應收/存貨成長 - 營收成長
ACCRUAL_THRESHOLDS = [(0.20, "顯著"), (0.10, "注意")]   # 應計比率
MIN_PEERS = 5               # 同業比較至少需要的公司數（不含自己）

QUARTER_COLUMNS = [
    "revenue", "gross_profit", "net_income", "cfo",
    "accounts_receivable", "inventory", "total_assets",
]


# ---------- 基礎工具 ----------
def _f(x) -> float | None:
    """轉成可 JSON 序列化的 float；NaN / inf 轉成 None。"""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def robust_z(x: float, history) -> float:
    """以中位數與 MAD 計算的穩健 z 分數；無法計算時回傳 NaN。"""
    if x is None or not np.isfinite(x):
        return float("nan")
    h = np.asarray(history, dtype=float)
    h = h[np.isfinite(h)]
    if h.size == 0:
        return float("nan")
    med = float(np.median(h))
    scale = MAD_SCALE * float(np.median(np.abs(h - med)))
    if scale == 0:
        scale = MEANAD_SCALE * float(np.mean(np.abs(h - med)))
    if scale == 0:
        return float("nan")
    return float((x - med) / scale)


def severity_from_z(z: float) -> str | None:
    if z is None or not np.isfinite(z):
        return None
    for threshold, label in SEVERITY_Z:
        if abs(z) >= threshold:
            return label
    return None


def severity_from_value(x: float, thresholds) -> str | None:
    if x is None or not np.isfinite(x):
        return None
    for threshold, label in thresholds:
        if x >= threshold:
            return label
    return None


def growth(curr: pd.Series, prev: pd.Series, min_base: float = 0.0) -> pd.Series:
    """curr / prev - 1；prev <= max(0, min_base) 或缺值時為 NaN。"""
    curr = curr.astype(float)
    prev = prev.astype(float)
    ok = prev > max(0.0, min_base)
    return (curr / prev.where(ok)) - 1.0


# ---------- 月營收 ----------
def monthly_series(rev_df: pd.DataFrame) -> pd.Series:
    """rev_df 欄位 revenue_year, revenue_month, revenue → 連續月份的 Series（缺月為 NaN）。"""
    if rev_df.empty:
        return pd.Series(dtype=float)
    idx = pd.PeriodIndex.from_fields(
        year=rev_df["revenue_year"].astype(int).to_numpy(),
        month=rev_df["revenue_month"].astype(int).to_numpy(),
        freq="M",
    )
    s = pd.Series(rev_df["revenue"].astype(float).to_numpy(), index=idx)
    s = s.groupby(level=0).last().sort_index()
    full = pd.period_range(s.index.min(), s.index.max(), freq="M")
    return s.reindex(full)


def revenue_yoy(rev_df: pd.DataFrame) -> pd.Series:
    s = monthly_series(rev_df)
    return growth(s, s.shift(12), MIN_BASE_REVENUE)


def detect_revenue_anomaly(
    symbol: str,
    rev_df: pd.DataFrame,
    as_of: pd.Period | None = None,
    peer_yoy: pd.Series | None = None,
) -> dict | None:
    """
    R-REV-YOY：單月營收年增率偏離自身歷史。
    peer_yoy：同產業其他公司同月份的年增率（index=symbol），可為 None。
    """
    s = monthly_series(rev_df)
    if s.empty:
        return None
    yoy = growth(s, s.shift(12), MIN_BASE_REVENUE)
    as_of = as_of if as_of is not None else yoy.index[-1]
    if as_of not in yoy.index or not np.isfinite(yoy[as_of]):
        return None

    hist = yoy[yoy.index < as_of].tail(REV_LOOKBACK).dropna()
    if len(hist) < REV_MIN_HIST:
        return None

    x = float(yoy[as_of])
    med = float(hist.median())
    z = robust_z(x, hist)
    if abs(x - med) < REV_MIN_ABS_DEV:
        return None
    sev = severity_from_z(z)
    if sev is None:
        return None

    evidence = {
        "revenue": _f(s[as_of]),
        "revenue_last_year": _f(s[as_of - 12]),
        "yoy": _f(x),
        "hist_median_yoy": _f(med),
        "n_hist": int(len(hist)),
        "peer_median_yoy": None,
        "peer_z": None,
        "n_peers": 0,
        "scope": "unknown",
    }
    if peer_yoy is not None:
        peers = peer_yoy.drop(labels=[symbol], errors="ignore").astype(float)
        peers = peers[np.isfinite(peers)]
        evidence["n_peers"] = int(len(peers))
        if len(peers) >= MIN_PEERS:
            pz = robust_z(x, peers)
            evidence["peer_median_yoy"] = _f(peers.median())
            evidence["peer_z"] = _f(pz)
            if np.isfinite(pz):
                evidence["scope"] = "company" if abs(pz) >= SEVERITY_Z[-1][0] else "industry"

    return {
        "symbol": symbol,
        "rule_id": "R-REV-YOY",
        "period": str(as_of),
        "value": _f(x),
        "baseline": _f(med),
        "z": _f(z),
        "severity": sev,
        "direction": "up" if x > med else "down",
        "evidence": evidence,
    }


# ---------- 季報 ----------
def decumulate_ytd(s: pd.Series) -> pd.Series:
    """
    累計數（Q1、H1、前三季、全年）→ 單季數。index 為季底日期或季 Period。
    前一季缺值時，該季單季數為 NaN（不猜）。假設會計年度 = 曆年。
    """
    if s.empty:
        return s.astype(float)
    q = s.copy()
    q.index = pd.PeriodIndex(q.index, freq="Q")
    q = q.groupby(level=0).last().sort_index().astype(float)
    full = pd.period_range(q.index.min(), q.index.max(), freq="Q")
    q = q.reindex(full)
    out = q - q.shift(1)
    is_q1 = np.asarray(full.quarter == 1)
    out[is_q1] = q[is_q1]
    return out


def to_quarter_frame(df: pd.DataFrame) -> pd.DataFrame:
    """index 轉成連續季 Period（缺季補 NaN），並補齊 QUARTER_COLUMNS。"""
    q = df.copy()
    q.index = pd.PeriodIndex(q.index, freq="Q")
    q = q.groupby(level=0).last().sort_index()
    full = pd.period_range(q.index.min(), q.index.max(), freq="Q")
    q = q.reindex(full)
    for c in QUARTER_COLUMNS:
        if c not in q.columns:
            q[c] = np.nan
    return q[QUARTER_COLUMNS].astype(float)


def quarterly_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """df：單季數字（cfo 必須已 decumulate），index 為季底日期或季 Period。"""
    q = to_quarter_frame(df)
    m = pd.DataFrame(index=q.index)
    rev = q["revenue"]
    m["gross_margin"] = q["gross_profit"] / rev.where(rev > 0)
    m["gm_yoy_pp"] = (m["gross_margin"] - m["gross_margin"].shift(4)) * 100.0
    m["rev_yoy"] = growth(rev, rev.shift(4))
    m["ar_yoy"] = growth(q["accounts_receivable"], q["accounts_receivable"].shift(4))
    m["inv_yoy"] = growth(q["inventory"], q["inventory"].shift(4))
    m["ar_div"] = m["ar_yoy"] - m["rev_yoy"]
    m["inv_div"] = m["inv_yoy"] - m["rev_yoy"]
    ni_ttm = q["net_income"].rolling(4, min_periods=4).sum()
    cfo_ttm = q["cfo"].rolling(4, min_periods=4).sum()
    avg_ta = (q["total_assets"] + q["total_assets"].shift(4)) / 2.0
    m["ni_ttm"] = ni_ttm
    m["cfo_ttm"] = cfo_ttm
    m["accruals"] = (ni_ttm - cfo_ttm) / avg_ta.where(avg_ta > 0)
    return m


def _flag(symbol, rule_id, period, value, baseline, z, sev, direction, evidence) -> dict:
    return {
        "symbol": symbol,
        "rule_id": rule_id,
        "period": str(period),
        "value": _f(value),
        "baseline": _f(baseline),
        "z": _f(z),
        "severity": sev,
        "direction": direction,
        "evidence": {k: (_f(v) if isinstance(v, (int, float, np.floating)) else v)
                     for k, v in evidence.items()},
    }


def detect_quarterly_anomalies(
    symbol: str, df: pd.DataFrame, as_of: pd.Period | None = None
) -> list[dict]:
    """R-GM-SHIFT、R-AR-DIV、R-INV-DIV、R-ACCRUAL。金融保險業不要呼叫（科目結構不同）。"""
    if df.empty:
        return []
    m = quarterly_metrics(df)
    as_of = as_of if as_of is not None else m.index[-1]
    if as_of not in m.index:
        return []
    row = m.loc[as_of]
    flags: list[dict] = []

    # R-GM-SHIFT：毛利率年變動偏離自身歷史
    x = row["gm_yoy_pp"]
    hist = m.loc[m.index < as_of, "gm_yoy_pp"].tail(Q_LOOKBACK).dropna()
    if np.isfinite(x) and len(hist) >= Q_MIN_HIST:
        med = float(hist.median())
        z = robust_z(x, hist)
        sev = severity_from_z(z)
        if sev == "注意" and abs(z) < GM_NOTE_MIN_Z:
            sev = None  # 毛利率注意級門檻單獨提到 z≥4.0（A-11 校準，D-A20）
        if sev and abs(x - med) >= GM_MIN_ABS_PP:
            flags.append(_flag(symbol, "R-GM-SHIFT", as_of, x, med, z, sev,
                               "up" if x > med else "down",
                               {"gross_margin": row["gross_margin"], "n_hist": int(len(hist))}))

    # R-AR-DIV / R-INV-DIV：應收、存貨成長遠快於營收（只看往上）
    for rule_id, col, yoy_col in (("R-AR-DIV", "ar_div", "ar_yoy"),
                                  ("R-INV-DIV", "inv_div", "inv_yoy")):
        x = row[col]
        sev = severity_from_value(x, DIV_THRESHOLDS)
        if sev:
            flags.append(_flag(symbol, rule_id, as_of, x, None, None, sev, "up",
                               {yoy_col: row[yoy_col], "rev_yoy": row["rev_yoy"]}))

    # R-ACCRUAL：近四季淨利遠高於營業現金流
    x = row["accruals"]
    sev = severity_from_value(x, ACCRUAL_THRESHOLDS)
    if sev:
        flags.append(_flag(symbol, "R-ACCRUAL", as_of, x, None, None, sev, "up",
                           {"ni_ttm": row["ni_ttm"], "cfo_ttm": row["cfo_ttm"]}))
    return flags


# ---------- 同業比較 ----------
def peer_robust_z(values: pd.Series, sector_map: dict, min_peers: int = MIN_PEERS) -> pd.Series:
    """每家公司相對「同產業其他公司」（不含自己）的穩健 z；同業不足為 NaN。"""
    vals = values.astype(float)
    out = {}
    for sym, v in vals.items():
        sector = sector_map.get(sym)
        if sector is None or not np.isfinite(v):
            out[sym] = float("nan")
            continue
        peers = [vals[p] for p in vals.index
                 if p != sym and sector_map.get(p) == sector and np.isfinite(vals[p])]
        out[sym] = robust_z(v, peers) if len(peers) >= min_peers else float("nan")
    return pd.Series(out, dtype=float)


# ---------- 新聞時間窗 ----------
def disclosure_deadline(rule_id: str, period: str) -> date:
    """法定公告期限：月營收 = 次月 10 日；Q1~Q3 = 季底 + 45 天；Q4 年報 = 次年 3/31。"""
    if rule_id == "R-REV-YOY":
        p = pd.Period(period, freq="M") + 1
        return date(p.year, p.month, 10)
    p = pd.Period(period, freq="Q")
    if p.quarter == 4:
        return date(p.year + 1, 3, 31)
    return p.end_time.date() + timedelta(days=45)


def news_window(rule_id: str, period: str, before: int = 30, after: int = 7) -> tuple[date, date]:
    d = disclosure_deadline(rule_id, period)
    return d - timedelta(days=before), d + timedelta(days=after)


# ---------- RAG 檢索 ----------
def top_k_by_cosine(query: np.ndarray, matrix: np.ndarray, k: int = 8) -> list[int]:
    """回傳 matrix 中與 query 最相似的前 k 列索引（由高到低）；零向量相似度視為 -1。"""
    if matrix.size == 0:
        return []
    q = np.asarray(query, dtype=float)
    mtx = np.asarray(matrix, dtype=float)
    qn = np.linalg.norm(q)
    rn = np.linalg.norm(mtx, axis=1)
    sims = np.full(len(mtx), -1.0)
    ok = (rn > 0) & (qn > 0)
    sims[ok] = (mtx[ok] @ q) / (rn[ok] * qn)
    order = np.argsort(-sims, kind="stable")
    return [int(i) for i in order[: max(0, k)]]


# ---------- AI 解讀驗證 ----------
CITE_RE = re.compile(r"\[(\d+)\]")
SPECULATION_MARKS = ("（推測）", "(推測)")
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s+")


def extract_section(text: str, heading: str) -> str | None:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lstrip("#").strip() == heading and line.lstrip().startswith("#"):
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if line.lstrip().startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def validate_explanation(text: str, n_sources: int) -> list[str]:
    """
    規則：(1) 所有 [n] 必須在 1..n_sources；
          (2) 「可能原因」每一點必須附 [n] 或標註（推測）。
    回傳問題清單；空 list 代表通過。
    """
    problems: list[str] = []
    for k in sorted({int(m) for m in CITE_RE.findall(text)}):
        if not 1 <= k <= n_sources:
            problems.append(f"引用 [{k}] 不存在")
    section = extract_section(text, "可能原因")
    if section is None:
        problems.append("缺少「可能原因」段落")
        return problems
    bullets = [ln.strip() for ln in section.splitlines() if BULLET_RE.match(ln)]
    if not bullets:
        problems.append("「可能原因」沒有條列內容")
    for b in bullets:
        if not CITE_RE.search(b) and not any(mark in b for mark in SPECULATION_MARKS):
            problems.append(f"未附來源也未標註推測：{b[:40]}")
    return problems


# ---------- 規則式備援解讀 ----------
RULE_NAMES = {
    "R-REV-YOY": "月營收年增率顯著變動",
    "R-GM-SHIFT": "毛利率顯著變動",
    "R-AR-DIV": "應收帳款成長快於營收",
    "R-INV-DIV": "存貨成長快於營收",
    "R-ACCRUAL": "帳面獲利與現金流落差大",
}

_CAUSES = {
    "R-REV-YOY": "一次性大額訂單或訂單遞延、合併或分割事業、產品週期轉換、去年同期基期特別高或特別低",
    "R-GM-SHIFT": "產品組合改變、原物料或匯率變動、產能利用率變化、一次性費用或存貨評價調整",
    "R-AR-DIV": "放寬客戶付款條件、季末集中出貨、主要客戶付款延遲",
    "R-INV-DIV": "為新產品或旺季提前備貨、需求不如預期造成庫存累積",
    "R-ACCRUAL": "應收帳款或存貨增加占用現金、認列尚未收現的收益、一次性業外收益",
}

_WATCH = {
    "R-REV-YOY": "下個月營收是否延續這個變化，以及公司是否發布說明這次變動的重大訊息。",
    "R-GM-SHIFT": "下一季毛利率是否回到過去區間，以及法說會對產品組合的說明。",
    "R-AR-DIV": "應收帳款收款天數的變化，以及下一季營業現金流量。",
    "R-INV-DIV": "存貨週轉天數的變化，以及是否提列存貨跌價損失。",
    "R-ACCRUAL": "接下來幾季營業現金流量是否追上帳面獲利。",
}

DISCLAIMER = "本內容僅為依公開財報數字計算的變動說明，不構成投資建議，也不代表對公司經營或誠信的判斷。"


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _what_happened(flag: dict) -> str:
    r, p, v, b, z, e = (flag["rule_id"], flag["period"], flag["value"],
                        flag["baseline"], flag["z"], flag["evidence"])
    if r == "R-REV-YOY":
        s = (f"{p} 單月營收年增率為 {_pct(v)}，明顯偏離該公司過去 {e['n_hist']} 個月的"
             f"中位數 {_pct(b)}（偏離程度 z={z:.1f}）。")
        if e.get("scope") == "company":
            s += f"同產業中位數為 {_pct(e['peer_median_yoy'])}，這次變動主要是這家公司自己的狀況。"
        elif e.get("scope") == "industry":
            s += f"同產業中位數為 {_pct(e['peer_median_yoy'])}，整個產業都有類似變化。"
        else:
            s += "同產業樣本不足，無法比較。"
        return s
    if r == "R-GM-SHIFT":
        return (f"{p} 毛利率比去年同季變動 {v:+.1f} 個百分點，過去同期變動的中位數為 "
                f"{b:+.1f} 個百分點（偏離程度 z={z:.1f}）。")
    if r == "R-AR-DIV":
        return (f"{p} 應收帳款年增 {_pct(e.get('ar_yoy'))}，營收年增 {_pct(e.get('rev_yoy'))}，"
                f"應收帳款的成長比營收快了 {v * 100:.0f} 個百分點。")
    if r == "R-INV-DIV":
        return (f"{p} 存貨年增 {_pct(e.get('inv_yoy'))}，營收年增 {_pct(e.get('rev_yoy'))}，"
                f"存貨的成長比營收快了 {v * 100:.0f} 個百分點。")
    if r == "R-ACCRUAL":
        return (f"截至 {p} 的近四季，稅後淨利與營業現金流量的差距約占平均總資產的 {v:.1%}，"
                f"代表帳面獲利中有較大比例還沒有變成現金。")
    raise ValueError(f"未知規則 {r}")


def fallback_explanation(flag: dict) -> str:
    r = flag["rule_id"]
    return "\n".join([
        "## 發生什麼",
        _what_happened(flag),
        "## 可能原因",
        f"- （推測）這類變動常見的原因包括：{_CAUSES[r]}。",
        "- （推測）目前沒有取得可以佐證的公開資訊，以上僅為一般情況，不代表這家公司的實際原因。",
        "## 需要留意",
        f"- {_WATCH[r]}",
        "## 資料來源",
        "- 本系統依公開財報數字計算",
        "## 重要提醒",
        DISCLAIMER,
    ])
