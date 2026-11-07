import json

import pytest

from app.services.chips_engine import summarize_chips


def _inst(days, foreign=0, trust=0, dealer=0):
    """產生 days 天、每天固定淨買賣超（股）的法人明細。"""
    return [{"date": f"2026-10-{d:02d}", "foreign": foreign, "trust": trust, "dealer": dealer}
            for d in range(1, days + 1)]


def _margin(series_margin, series_short):
    return [{"date": f"2026-10-{i+1:02d}", "margin_lots": m, "short_lots": s}
            for i, (m, s) in enumerate(zip(series_margin, series_short))]


def test_empty_inputs_give_none_fields():
    s = summarize_chips("2330.TW", [], [], window_days=20)
    assert s["symbol"] == "2330.TW"
    assert s["inst_net_lots"] is None
    assert s["margin_balance_lots"] is None
    json.dumps(s)  # 必須可序列化


def test_institutional_net_sums_and_lots():
    # 連 5 天外資每天買超 100 張（100*1000 股）
    s = summarize_chips("2330.TW", _inst(5, foreign=100_000), [], window_days=20)
    assert s["foreign_net_lots"] == pytest.approx(500.0)   # 5 天 × 100 張
    assert s["inst_net_lots"] == pytest.approx(500.0)
    assert s["inst_direction"] == "up"
    assert s["as_of"] == "2026-10-05"


def test_direction_down_and_flat():
    down = summarize_chips("X", _inst(5, foreign=-100_000), [], window_days=20)
    assert down["inst_direction"] == "down"
    # 合計 40 張 < 50 張門檻 → 持平
    flat = summarize_chips("Y", _inst(2, foreign=20_000), [], window_days=20)
    assert flat["inst_direction"] == "flat"


def test_window_only_counts_recent_days():
    # 30 天買超，window=20 → 只算最近 20 天
    s = summarize_chips("Z", _inst(30, trust=10_000), [], window_days=20)
    assert s["trust_net_lots"] == pytest.approx(200.0)  # 20 天 × 10 張


def test_margin_change_and_ratio():
    s = summarize_chips(
        "2317.TW",
        [],
        _margin([1000, 1020, 1060], [100, 110, 120]),
        window_days=20,
    )
    assert s["margin_balance_lots"] == pytest.approx(1060.0)
    assert s["margin_change_lots"] == pytest.approx(60.0)   # 1060 - 1000
    assert s["short_change_lots"] == pytest.approx(20.0)    # 120 - 100
    assert s["margin_short_ratio"] == pytest.approx(round(1060 / 120, 2))


def test_margin_ratio_none_when_no_short():
    s = summarize_chips("A", [], _margin([500, 510], [0, 0]), window_days=20)
    assert s["margin_short_ratio"] is None
