import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services.anomaly_engine import (
    RULE_NAMES,
    decumulate_ytd,
    detect_quarterly_anomalies,
    detect_revenue_anomaly,
    disclosure_deadline,
    fallback_explanation,
    growth,
    news_window,
    peer_robust_z,
    quarterly_metrics,
    revenue_yoy,
    robust_z,
    severity_from_z,
    top_k_by_cosine,
    validate_explanation,
)
from app.services.guard import find_violations


# ---------- 測試資料產生 ----------
def make_revenue(n_months=48, spike_last=None, seed=0, drop_month=None):
    """穩定成長約 5%/年 + 小雜訊；可在最後一個月製造暴增。"""
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2022-01", periods=n_months, freq="M")
    base = 1_000_000 * (1.05 ** (np.arange(n_months) / 12)) * (1 + rng.normal(0, 0.03, n_months))
    if spike_last is not None:
        base[-1] = base[-13] * (1 + spike_last)
    df = pd.DataFrame({"revenue_year": periods.year, "revenue_month": periods.month, "revenue": base})
    if drop_month is not None:
        df = df[~((df.revenue_year == drop_month.year) & (df.revenue_month == drop_month.month))]
    return df


def make_quarters(n=16, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2022Q1", periods=n, freq="Q")
    rev = 10_000 * (1 + rng.normal(0, 0.02, n))
    return pd.DataFrame({
        "revenue": rev,
        "gross_profit": rev * (0.30 + rng.normal(0, 0.005, n)),
        "net_income": rev * 0.10,
        "cfo": rev * 0.10,
        "accounts_receivable": rev * 0.5,
        "inventory": rev * 0.4,
        "total_assets": np.full(n, 50_000.0),
    }, index=idx)


# ---------- robust z ----------
def test_robust_z_known():
    # 中位數 3、MAD 1 → z = (10-3)/(1.4826*1)
    assert robust_z(10, [1, 2, 3, 4, 5]) == pytest.approx(7 / 1.4826)


def test_robust_z_mad_zero_falls_back_to_meanad():
    h = [1, 1, 1, 1, 5]  # MAD = 0，MeanAD = 0.8
    assert robust_z(3, h) == pytest.approx((3 - 1) / (1.2533 * 0.8))


def test_robust_z_constant_history_nan():
    assert np.isnan(robust_z(3, [2, 2, 2]))


def test_robust_z_ignores_nan():
    assert robust_z(10, [1, 2, np.nan, 3, 4, 5]) == pytest.approx(7 / 1.4826)


def test_severity_levels():
    assert severity_from_z(3.0) is None
    assert severity_from_z(-3.6) == "注意"
    assert severity_from_z(5.0) == "顯著"
    assert severity_from_z(9.0) == "極端"
    assert severity_from_z(float("nan")) is None


def test_growth_base_guard():
    g = growth(pd.Series([110.0, 5.0, 3.0]), pd.Series([100.0, 0.0, -1.0]))
    assert g.iloc[0] == pytest.approx(0.10)
    assert np.isnan(g.iloc[1]) and np.isnan(g.iloc[2])


# ---------- 月營收 ----------
def test_revenue_yoy_uses_calendar_months_not_rows():
    df = make_revenue(36, drop_month=pd.Period("2023-06", freq="M"))
    yoy = revenue_yoy(df)
    # 2023-06 缺 → 2023-06 與 2024-06 的年增率都應為 NaN，而不是錯位成別的月份
    assert np.isnan(yoy[pd.Period("2023-06", freq="M")])
    assert np.isnan(yoy[pd.Period("2024-06", freq="M")])
    assert np.isfinite(yoy[pd.Period("2024-07", freq="M")])


def test_revenue_spike_flagged():
    flag = detect_revenue_anomaly("2330.TW", make_revenue(48, spike_last=1.0))
    assert flag is not None
    assert flag["rule_id"] == "R-REV-YOY"
    assert flag["direction"] == "up"
    assert flag["value"] == pytest.approx(1.0)
    assert flag["severity"] in ("注意", "顯著", "極端")
    json.dumps(flag, ensure_ascii=False)


def test_revenue_drop_flagged():
    flag = detect_revenue_anomaly("X", make_revenue(48, spike_last=-0.6))
    assert flag is not None and flag["direction"] == "down"


def test_revenue_normal_not_flagged():
    assert detect_revenue_anomaly("X", make_revenue(48)) is None


def test_revenue_short_history_not_flagged():
    # 20 個月 → 只有 8 個年增率，不到 REV_MIN_HIST
    assert detect_revenue_anomaly("X", make_revenue(20, spike_last=2.0)) is None


def test_revenue_materiality_threshold():
    # 歷史雜訊極小時，+10% 雖然 z 很大，但沒超過 20pp 重大性門檻 → 不報
    periods = pd.period_range("2022-01", periods=48, freq="M")
    rev = 1_000_000 * (1.05 ** (np.arange(48) / 12))
    rev[-1] = rev[-13] * 1.15
    df = pd.DataFrame({"revenue_year": periods.year, "revenue_month": periods.month, "revenue": rev})
    assert detect_revenue_anomaly("X", df) is None


def test_revenue_peer_scope():
    df = make_revenue(48, spike_last=1.0)
    alone = pd.Series({"A": 0.05, "B": 0.04, "C": 0.06, "D": 0.03, "E": 0.05, "X": 1.0})
    whole = pd.Series({"A": 0.95, "B": 1.05, "C": 0.90, "D": 1.10, "E": 1.00, "X": 1.0})
    assert detect_revenue_anomaly("X", df, peer_yoy=alone)["evidence"]["scope"] == "company"
    assert detect_revenue_anomaly("X", df, peer_yoy=whole)["evidence"]["scope"] == "industry"
    few = pd.Series({"A": 0.05, "X": 1.0})
    assert detect_revenue_anomaly("X", df, peer_yoy=few)["evidence"]["scope"] == "unknown"


def test_revenue_empty():
    empty = pd.DataFrame(columns=["revenue_year", "revenue_month", "revenue"])
    assert detect_revenue_anomaly("X", empty) is None


# ---------- 季報 ----------
def test_decumulate_ytd():
    idx = pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"])
    s = pd.Series([10.0, 25.0, 45.0, 70.0, 12.0], index=idx)
    out = decumulate_ytd(s)
    assert list(out.to_numpy()) == pytest.approx([10, 15, 20, 25, 12])


def test_decumulate_missing_prior_quarter_is_nan():
    idx = pd.to_datetime(["2025-03-31", "2025-09-30"])
    out = decumulate_ytd(pd.Series([10.0, 45.0], index=idx))
    assert np.isnan(out[pd.Period("2025Q2", freq="Q")])
    assert np.isnan(out[pd.Period("2025Q3", freq="Q")])


def test_quarterly_normal_no_flags():
    assert detect_quarterly_anomalies("X", make_quarters()) == []


def test_ar_divergence_flag():
    q = make_quarters()
    q.iloc[-1, q.columns.get_loc("accounts_receivable")] *= 1.8  # 應收暴增 80%
    flags = {f["rule_id"]: f for f in detect_quarterly_anomalies("X", q)}
    assert "R-AR-DIV" in flags
    assert flags["R-AR-DIV"]["severity"] == "顯著"


def test_inventory_divergence_flag():
    q = make_quarters()
    q.iloc[-1, q.columns.get_loc("inventory")] *= 1.4
    assert "R-INV-DIV" in {f["rule_id"] for f in detect_quarterly_anomalies("X", q)}


def test_gross_margin_shift_flag():
    q = make_quarters()
    q.iloc[-1, q.columns.get_loc("gross_profit")] = q["revenue"].iloc[-1] * 0.20  # 30% → 20%
    flags = {f["rule_id"]: f for f in detect_quarterly_anomalies("X", q)}
    assert "R-GM-SHIFT" in flags and flags["R-GM-SHIFT"]["direction"] == "down"


def test_accrual_flag_and_value():
    q = make_quarters()
    q["cfo"] = 0.0  # 完全沒有現金流 → 應計 = TTM 淨利 / 平均總資產
    flags = {f["rule_id"]: f for f in detect_quarterly_anomalies("X", q)}
    m = quarterly_metrics(q)
    expected = q["net_income"].iloc[-4:].sum() / 50_000.0
    assert m["accruals"].iloc[-1] == pytest.approx(expected)
    assert "R-ACCRUAL" not in flags or flags["R-ACCRUAL"]["value"] == pytest.approx(expected)


def test_accrual_flag_triggers():
    q = make_quarters()
    q["cfo"] = -q["net_income"]  # 淨利為正、現金流為負
    assert "R-ACCRUAL" in {f["rule_id"] for f in detect_quarterly_anomalies("X", q)}


def test_ttm_requires_consecutive_quarters():
    q = make_quarters().drop(index=pd.Period("2025Q2", freq="Q"))
    m = quarterly_metrics(q)
    assert np.isnan(m.loc[pd.Period("2025Q3", freq="Q"), "ni_ttm"])


def test_zero_revenue_no_crash():
    q = make_quarters()
    q.iloc[-1, q.columns.get_loc("revenue")] = 0.0
    flags = detect_quarterly_anomalies("X", q)
    json.dumps(flags, ensure_ascii=False)


def test_missing_columns_ok():
    q = make_quarters()[["revenue", "gross_profit"]]
    flags = detect_quarterly_anomalies("X", q)
    assert all(f["rule_id"] == "R-GM-SHIFT" for f in flags)


# ---------- 同業 ----------
def test_peer_robust_z_excludes_self_and_needs_peers():
    vals = pd.Series({"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "X": 20, "Y": 1})
    sectors = {"A": "s", "B": "s", "C": "s", "D": "s", "E": "s", "X": "s", "Y": "t"}
    z = peer_robust_z(vals, sectors)
    assert z["X"] == pytest.approx(robust_z(20, [1, 2, 3, 4, 5]))
    assert np.isnan(z["Y"])


# ---------- 新聞時間窗 ----------
def test_disclosure_deadlines():
    assert disclosure_deadline("R-REV-YOY", "2026-01") == date(2026, 2, 10)
    assert disclosure_deadline("R-REV-YOY", "2025-12") == date(2026, 1, 10)
    assert disclosure_deadline("R-GM-SHIFT", "2026Q1") == date(2026, 5, 15)
    assert disclosure_deadline("R-AR-DIV", "2026Q2") == date(2026, 8, 14)
    assert disclosure_deadline("R-AR-DIV", "2026Q3") == date(2026, 11, 14)
    assert disclosure_deadline("R-ACCRUAL", "2025Q4") == date(2026, 3, 31)


def test_news_window():
    start, end = news_window("R-REV-YOY", "2026-01")
    assert start == date(2026, 1, 11) and end == date(2026, 2, 17)


# ---------- 檢索 ----------
def test_top_k_by_cosine():
    m = np.array([[1, 0], [0, 1], [0.9, 0.1], [0, 0]])
    assert top_k_by_cosine(np.array([1, 0]), m, k=2) == [0, 2]
    assert top_k_by_cosine(np.array([1, 0]), m, k=10)[-1] == 3  # 零向量排最後
    assert top_k_by_cosine(np.array([1, 0]), np.empty((0, 2)), k=3) == []


# ---------- 引用驗證 ----------
GOOD = """## 發生什麼
營收年增 100%。
## 可能原因
- 公司公告取得大客戶訂單 [1]
- （推測）去年同期基期偏低
## 需要留意
- 下月營收
## 資料來源
[1] 新聞標題
"""


def test_validate_good():
    assert validate_explanation(GOOD, n_sources=1) == []


def test_validate_bad_citation_number():
    assert any("[3]" in p for p in validate_explanation(GOOD.replace("[1]", "[3]"), n_sources=1))


def test_validate_unsupported_claim():
    bad = GOOD.replace("- （推測）去年同期基期偏低", "- 去年同期基期偏低")
    assert any("未附來源" in p for p in validate_explanation(bad, n_sources=1))


def test_validate_missing_section():
    assert validate_explanation("## 發生什麼\n很多", 0) == ["缺少「可能原因」段落"]


def test_validate_numbered_bullets():
    t = "## 可能原因\n1. 訂單增加 [1]\n2) 新產品 [2]\n## 需要留意\n- x"
    assert validate_explanation(t, 2) == []


# ---------- 備援解讀 ----------
def _sample_flags():
    flags = [detect_revenue_anomaly("X", make_revenue(48, spike_last=1.0))]
    q = make_quarters()
    q.iloc[-1, q.columns.get_loc("accounts_receivable")] *= 1.8
    q.iloc[-1, q.columns.get_loc("inventory")] *= 1.8
    q.iloc[-1, q.columns.get_loc("gross_profit")] = q["revenue"].iloc[-1] * 0.20
    q["cfo"] = -q["net_income"]
    flags += detect_quarterly_anomalies("X", q)
    return flags


def test_sample_covers_all_rules():
    assert {f["rule_id"] for f in _sample_flags()} == set(RULE_NAMES)


@pytest.mark.parametrize("flag", _sample_flags(), ids=lambda f: f["rule_id"])
def test_fallback_passes_validator_and_guard(flag):
    text = fallback_explanation(flag)
    assert validate_explanation(text, n_sources=0) == []
    assert find_violations(text) == []
    assert "不構成投資建議" in text


def test_guard_accusation_words():
    assert find_violations("這家公司可能造假") == ["造假"]
    assert find_violations("營收年增率明顯上升") == []
