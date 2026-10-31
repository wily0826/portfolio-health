import json

import numpy as np
import pandas as pd
import pytest

from app.services.risk_engine import (
    InsufficientDataError,
    analyze,
    annualized_return,
    avg_pairwise_correlation,
    compute_weights,
    hhi,
    historical_var,
    max_drawdown,
    risk_score,
    SCORE_CONFIG,
)


def make_prices(n_days=300, symbols=("2330.TW", "2317.TW", "2412.TW"), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n_days)
    data = {}
    for i, s in enumerate(symbols):
        r = rng.normal(0.0005, 0.01 + 0.005 * i, n_days)
        data[s] = 100 * np.cumprod(1 + r)
    return pd.DataFrame(data, index=idx)


def test_score_weights_sum_to_one():
    assert sum(w for _, _, w in SCORE_CONFIG.values()) == pytest.approx(1.0)


def test_hhi_equal_two():
    assert hhi(pd.Series([0.5, 0.5])) == pytest.approx(0.5)


def test_hhi_single():
    assert hhi(pd.Series([1.0])) == pytest.approx(1.0)


def test_mdd_known():
    assert max_drawdown(pd.Series([0.10, -0.20])) == pytest.approx(-0.2)


def test_mdd_first_day_drop():
    assert max_drawdown(pd.Series([-0.10, 0.05])) == pytest.approx(-0.10)


def test_mdd_never_down():
    assert max_drawdown(pd.Series([0.01, 0.02])) == pytest.approx(0.0)


def test_annual_return_zero():
    assert annualized_return(pd.Series([0.0] * 252)) == pytest.approx(0.0)


def test_annual_return_known():
    # 252 天每天 +0.1% → (1.001)^252 - 1
    assert annualized_return(pd.Series([0.001] * 252)) == pytest.approx(1.001 ** 252 - 1)


def test_var_known():
    r = pd.Series(np.linspace(-0.05, 0.05, 101))  # 5th percentile = -0.045
    assert historical_var(r) == pytest.approx(0.045)


def test_var_no_loss_is_zero():
    assert historical_var(pd.Series([0.01] * 100)) == 0.0


def test_weights_sum_and_values():
    h = pd.DataFrame({"symbol": ["A", "B"], "shares": [10, 30]})
    w = compute_weights(h, pd.Series({"A": 30.0, "B": 10.0}))
    assert w.sum() == pytest.approx(1.0)
    assert w["A"] == pytest.approx(0.5)


def test_weights_duplicate_symbol_merged():
    h = pd.DataFrame({"symbol": ["A", "A", "B"], "shares": [5, 5, 10]})
    w = compute_weights(h, pd.Series({"A": 1.0, "B": 1.0}))
    assert w["A"] == pytest.approx(0.5)


def test_missing_price_raises():
    h = pd.DataFrame({"symbol": ["A", "Z"], "shares": [1, 1]})
    with pytest.raises(ValueError):
        compute_weights(h, pd.Series({"A": 1.0}))


def test_insufficient_data():
    prices = make_prices(30)
    h = pd.DataFrame({"symbol": list(prices.columns), "shares": [1, 1, 1]})
    with pytest.raises(InsufficientDataError):
        analyze(h, prices, {})


def test_single_holding_no_nan():
    prices = make_prices(300, symbols=("2330.TW",))
    h = pd.DataFrame({"symbol": ["2330.TW"], "shares": [1000]})
    out = analyze(h, prices, {"2330.TW": "半導體業"})
    m = out["metrics"]
    assert m["avg_correlation"] == 0.0
    assert m["top1_weight"] == pytest.approx(1.0)
    assert m["effective_n"] == pytest.approx(1.0)
    flat = [v for v in m.values() if isinstance(v, float)]
    assert not any(np.isnan(flat))


def test_correlation_perfect():
    r = pd.DataFrame({"A": [0.01, -0.02, 0.03, 0.0], "B": [0.02, -0.04, 0.06, 0.0]})
    assert avg_pairwise_correlation(r) == pytest.approx(1.0)


def test_portfolio_vol_matches_independent_calc():
    prices = make_prices(300)
    shares = [100, 200, 300]
    h = pd.DataFrame({"symbol": list(prices.columns), "shares": shares})
    m = analyze(h, prices, {})["metrics"]
    # 獨立計算：w' Σ w
    last = prices.iloc[-1].to_numpy()
    w = np.array(shares) * last / (np.array(shares) * last).sum()
    rets = prices.tail(253).pct_change().dropna().to_numpy()
    cov = np.cov(rets, rowvar=False, ddof=1)
    expected = np.sqrt(w @ cov @ w) * np.sqrt(252)
    assert m["volatility"] == pytest.approx(expected, rel=1e-9)
    assert m["n_observations"] == 252


def test_sector_none_goes_unclassified():
    prices = make_prices(300)
    h = pd.DataFrame({"symbol": list(prices.columns), "shares": [1, 1, 1]})
    m = analyze(h, prices, {"2330.TW": "半導體業", "2317.TW": None})["metrics"]
    assert "未分類" in m["sector_weights"]
    assert sum(m["sector_weights"].values()) == pytest.approx(1.0, abs=1e-5)


def test_short_gap_ffill_ok_long_gap_raises():
    prices = make_prices(300)
    p1 = prices.copy()
    p1.iloc[-3:, 0] = np.nan  # 停牌 3 天 → 可前值填補
    h = pd.DataFrame({"symbol": list(prices.columns), "shares": [1, 1, 1]})
    analyze(h, p1, {})
    p2 = prices.copy()
    p2.iloc[-10:, 0] = np.nan  # 停牌 10 天 → 應拋錯
    with pytest.raises(ValueError):
        analyze(h, p2, {})


def test_score_bounds_and_json():
    for seed in range(20):
        prices = make_prices(300, seed=seed)
        h = pd.DataFrame({"symbol": list(prices.columns), "shares": [1, 5, 50]})
        out = analyze(h, prices, {"2330.TW": "半導體業"})
        s = out["metrics"]["score"]
        assert 0 <= s["score"] <= 100
        assert s["level"] in ("低", "中", "高")
        json.dumps(out, ensure_ascii=False)  # 必須可序列化


def test_score_extremes():
    low = {"top1_weight": 0, "sector_hhi": 0, "volatility": 0, "max_drawdown_abs": 0, "avg_correlation": 0}
    high = {k: 10 for k in low}
    assert risk_score(low)["score"] == 0
    assert risk_score(high)["score"] == 100
    assert risk_score(high)["level"] == "高"


def test_concentrated_scores_higher_than_diversified():
    prices = make_prices(300)
    syms = list(prices.columns)
    conc = analyze(pd.DataFrame({"symbol": syms, "shares": [1000, 1, 1]}), prices,
                   {s: "半導體業" for s in syms})["metrics"]["score"]["score"]
    div = analyze(pd.DataFrame({"symbol": syms, "shares": [1, 1, 1]}), prices,
                  {syms[0]: "A", syms[1]: "B", syms[2]: "C"})["metrics"]["score"]["score"]
    assert conc > div
