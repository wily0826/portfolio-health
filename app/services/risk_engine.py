# risk_engine.py
# 純函式風險計算引擎：不碰 DB、不碰網路、不碰 LLM（見 SPEC §4 設計原則）。
# 數字一律由此處確定性計算，LLM 只負責解讀（D-005）。
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
LOOKBACK_DAYS = 252
MIN_OBS = 60
RISK_FREE_RATE = 0.015

# 指標名: (low, high, 權重)。<= low 得 0 分，>= high 得 100 分，中間線性。權重總和必須為 1。
# 2026-11：移除平均相關係數子分數後，其餘四項權重重新正規化為總和 1（D-A21）。
SCORE_CONFIG = {
    "top1_weight": (0.10, 0.50, 0.30),
    "sector_hhi": (0.15, 0.50, 0.25),
    "volatility": (0.10, 0.40, 0.30),
    "max_drawdown_abs": (0.05, 0.40, 0.15),
}


class InsufficientDataError(ValueError):
    """歷史資料不足以計算指標。"""


def compute_weights(holdings: pd.DataFrame, last_prices_twd: pd.Series) -> pd.Series:
    """holdings 需有欄位 symbol, shares；last_prices_twd 的 index 為 symbol。回傳權重（總和 1）。"""
    shares = holdings.groupby("symbol")["shares"].sum().astype(float)
    prices = last_prices_twd.reindex(shares.index).astype(float)
    if prices.isna().any():
        raise ValueError(f"缺少價格: {list(prices[prices.isna()].index)}")
    values = shares * prices
    total = float(values.sum())
    if total <= 0:
        raise ValueError("總市值必須大於 0")
    return values / total


def asset_returns(prices_twd: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """取共同交易日、最近 LOOKBACK_DAYS 天的個股日報酬。"""
    prices = prices_twd[symbols].sort_index().dropna(how="any").tail(LOOKBACK_DAYS + 1)
    rets = prices.pct_change().dropna()
    if len(rets) < MIN_OBS:
        raise InsufficientDataError(
            f"共同交易日只有 {len(rets)} 天，至少需要 {MIN_OBS} 天"
        )
    return rets


def portfolio_returns(rets: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """固定權重的組合日報酬。"""
    return rets.mul(weights.reindex(rets.columns), axis=1).sum(axis=1)


def annualized_volatility(r: pd.Series) -> float:
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def annualized_return(r: pd.Series) -> float:
    n = len(r)
    growth = float(np.prod(1.0 + r.to_numpy()))
    return float(growth ** (TRADING_DAYS / n) - 1.0)


def sharpe_ratio(r: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    vol = annualized_volatility(r)
    if vol == 0:
        return 0.0
    return float((annualized_return(r) - rf) / vol)


def max_drawdown(r: pd.Series) -> float:
    """回傳值 <= 0。財富曲線從 1.0 起算，所以第一天就下跌也會被計入。"""
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + r.to_numpy())))
    peak = np.maximum.accumulate(wealth)
    return float((wealth / peak - 1.0).min())


def historical_var(r: pd.Series, level: float = 0.95) -> float:
    """單日歷史 VaR，以正數損失表示；若為負（沒有虧損）則取 0。"""
    q = float(np.percentile(r.to_numpy(), (1.0 - level) * 100.0))
    return max(0.0, -q)


def hhi(w: pd.Series) -> float:
    return float((w ** 2).sum())


def sector_weights(weights: pd.Series, sector_map: dict[str, str | None]) -> pd.Series:
    keys = np.array([sector_map.get(s) or "未分類" for s in weights.index])
    return weights.groupby(keys).sum()


def _scale(x: float, low: float, high: float) -> float:
    return float(np.clip((x - low) / (high - low), 0.0, 1.0) * 100.0)


def risk_score(metrics: dict) -> dict:
    subs = {k: _scale(metrics[k], lo, hi) for k, (lo, hi, _) in SCORE_CONFIG.items()}
    total = sum(subs[k] * w for k, (_, _, w) in SCORE_CONFIG.items())
    level = "低" if total < 30 else ("中" if total < 60 else "高")
    return {
        "score": round(total, 1),
        "level": level,
        "sub_scores": {k: round(v, 1) for k, v in subs.items()},
    }


def analyze(
    holdings: pd.DataFrame,
    prices_twd: pd.DataFrame,
    sector_map: dict[str, str | None],
    rf: float = RISK_FREE_RATE,
) -> dict:
    """
    holdings:   欄位 symbol, shares
    prices_twd: index=日期(DatetimeIndex), columns=symbol, 值=以 TWD 計的還原價
    sector_map: {symbol: 產業或 None}
    回傳 {"metrics": {...}, "curve": [{"date","value"}...]}
    metrics 可 JSON 序列化；curve 只給前端畫圖，不要餵給 LLM。
    """
    prices = prices_twd.sort_index().ffill(limit=5)  # 容忍最多 5 天缺價（停牌/假日錯位）
    weights = compute_weights(holdings, prices.iloc[-1])
    rets = asset_returns(prices, list(weights.index))
    p_rets = portfolio_returns(rets, weights)
    sec_w = sector_weights(weights, sector_map)

    stock_hhi = hhi(weights)
    mdd = max_drawdown(p_rets)

    metrics = {
        "data_as_of": str(pd.Timestamp(prices.index[-1]).date()),
        "n_holdings": int(len(weights)),
        "n_observations": int(len(p_rets)),
        "lookback_note": "以目前權重回溯計算，非使用者實際歷史績效",
        "is_single_holding": bool(len(weights) == 1),
        "weights": {str(k): round(float(v), 6) for k, v in weights.items()},
        "sector_weights": {str(k): round(float(v), 6) for k, v in sec_w.items()},
        "top1_symbol": str(weights.idxmax()),
        "top1_weight": float(weights.max()),
        "stock_hhi": stock_hhi,
        "effective_n": float(1.0 / stock_hhi),
        "sector_hhi": hhi(sec_w),
        "volatility": annualized_volatility(p_rets),
        "annual_return": annualized_return(p_rets),
        "sharpe": sharpe_ratio(p_rets, rf),
        "max_drawdown": mdd,
        "max_drawdown_abs": abs(mdd),
        "var_95_1d": historical_var(p_rets, 0.95),
    }
    metrics["score"] = risk_score(metrics)

    wealth = (1.0 + p_rets).cumprod()
    curve = [
        {"date": str(pd.Timestamp(d).date()), "value": round(float(v), 4)}
        for d, v in wealth.items()
    ]
    return {"metrics": metrics, "curve": curve}
