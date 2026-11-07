# verify_engine.py — T-10：風險引擎獨立驗算
# 用 numpy 第一原理把每個指標「重新算一遍」（不重用 risk_engine 的指標函式），
# 與 analyze() 的輸出逐項比對。目的：證明引擎數字正確、可重現（答辯素材）。
# 用法：python -m scripts.verify_engine
from __future__ import annotations

import numpy as np
import pandas as pd

from app.db import get_conn
from app.services.price_service import get_prices_df, get_sector_map
from app.services.risk_engine import (LOOKBACK_DAYS, RISK_FREE_RATE, TRADING_DAYS,
                                      analyze)

TOL = 1e-9  # 相對誤差容忍


def _independent_metrics(symbols, shares, prices_df, sector_map) -> dict:
    """完全獨立的重算（只用 numpy 基本運算），刻意不呼叫 risk_engine 的指標函式。"""
    prices = prices_df.sort_index().ffill(limit=5)

    # 權重：V_i = 股數 × 最新價；w = V / ΣV
    last = prices.iloc[-1]
    q = pd.Series(shares, index=symbols, dtype=float).groupby(level=0).sum()
    v = q * last.reindex(q.index).astype(float)
    w = (v / v.sum())

    # 個股日報酬：取共同交易日、最近 252+1 天
    sub = prices[list(w.index)].sort_index().dropna(how="any").tail(LOOKBACK_DAYS + 1)
    rets = sub.pct_change().dropna()
    R = rets.to_numpy()                      # (n, k)
    wv = w.reindex(rets.columns).to_numpy()  # (k,)

    # 組合日報酬：每日 Σ w_i r_i
    p = R @ wv                               # (n,)
    n = len(p)

    # 波動度（年化，樣本標準差 ddof=1）
    vol = np.std(p, ddof=1) * np.sqrt(TRADING_DAYS)
    # 年化報酬（幾何）
    ann = float(np.prod(1.0 + p)) ** (TRADING_DAYS / n) - 1.0
    # 夏普
    sharpe = (ann - RISK_FREE_RATE) / vol if vol else 0.0
    # 最大回撤（獨立：財富曲線從 1 起算，逐日比對歷史高點）
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + p)))
    peak = -np.inf
    mdd = 0.0
    for x in wealth:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1.0)
    # 歷史 VaR 95%（單日）
    var = max(0.0, -float(np.percentile(p, 5.0)))
    # 集中度
    hhi = float(np.sum(wv ** 2))
    eff = 1.0 / hhi
    # 產業 HHI
    sec = {}
    for sym, wi in zip(w.index, wv):
        key = sector_map.get(sym) or "未分類"
        sec[key] = sec.get(key, 0.0) + float(wi)
    sector_hhi = float(np.sum(np.array(list(sec.values())) ** 2))

    return {
        "top1_weight": float(w.max()),
        "stock_hhi": hhi,
        "effective_n": eff,
        "sector_hhi": sector_hhi,
        "volatility": float(vol),
        "annual_return": float(ann),
        "sharpe": float(sharpe),
        "max_drawdown": float(mdd),
        "var_95_1d": var,
        "n_observations": n,
    }


def _fmt(x) -> str:
    return f"{x:.6f}" if isinstance(x, float) else str(x)


def verify_portfolio(name, rows) -> bool:
    symbols = [r["symbol"] for r in rows]
    shares = [float(r["shares"]) for r in rows]
    prices = get_prices_df(symbols)
    sector_map = get_sector_map(symbols)

    eng = analyze(pd.DataFrame({"symbol": symbols, "shares": shares}),
                  prices, sector_map)["metrics"]
    ind = _independent_metrics(symbols, shares, prices, sector_map)

    print(f"\n{'='*66}\n{name}（{', '.join(symbols)}）\n{'='*66}")
    print(f"{'指標':<16}{'引擎':>16}{'獨立算':>16}{'相對誤差':>14}")
    ok = True
    for k in ["top1_weight", "stock_hhi", "effective_n", "sector_hhi", "volatility",
              "annual_return", "sharpe", "max_drawdown", "var_95_1d",
              "n_observations"]:
        a, b = eng[k], ind[k]
        denom = max(abs(a), 1e-12)
        rel = abs(a - b) / denom
        flag = "✓" if rel <= TOL else "✗ 不符"
        ok = ok and rel <= TOL
        print(f"{k:<16}{_fmt(a):>16}{_fmt(b):>16}{rel:>13.2e} {flag}")
    return ok


def main() -> int:
    conn = get_conn()
    try:
        users = conn.execute(
            "SELECT id, display_name FROM users WHERE email LIKE 'demo-%' ORDER BY id"
        ).fetchall()
        portfolios = []
        for u in users:
            rows = conn.execute(
                "SELECT symbol, shares FROM holdings WHERE user_id = ? ORDER BY symbol",
                (u["id"],),
            ).fetchall()
            if rows:
                portfolios.append((u["display_name"], [dict(r) for r in rows]))
    finally:
        conn.close()

    if not portfolios:
        print("找不到 demo-* 帳號的持股，請先執行 python -m scripts.seed_demo")
        return 1

    all_ok = True
    for name, rows in portfolios:
        all_ok = verify_portfolio(name, rows) and all_ok

    print(f"\n{'='*66}")
    print("✅ 全部指標與獨立重算一致（相對誤差 ≤ 1e-9）" if all_ok
          else "✗ 有指標不一致，請檢查")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
