# synthetic_fundamentals.py
# 離線合成財報資料源（展示 / 測試用）：依 symbol 產生「可重現」的月營收與三大報表，
# 讓財報變動偵測在沒有 FinMind token、沒有網路時也能完整端到端展示（SPEC-anomaly §5）。
#
# 注意：這不是真實財報，簡報時必須說明。真實資料請用 FUNDAMENTALS_SOURCE=finmind（需先完成 A-02）。
#
# 為了讓展示看得到各類旗標，對少數「展示股」刻意製造顯著變動（見 _ANOMALY_SCRIPT）；
# 其餘公司維持平穩成長，不會觸發任何規則。產業分類沿用股價合成源的 catalog，確保同業比較一致。
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .synthetic import catalog_info

# 月營收期數（6 年）與季報期數（4 年）
_N_MONTHS = 72
_N_QUARTERS = 16

# 不產生財報的產業（ETF 無財報；金融保險業科目結構不同，不在模組範圍內）
_SKIP_SECTORS = {"ETF", "金融保險業"}

# 各產業的月營收基準量級（TWD，僅為讓數字看起來合理，不影響偵測邏輯）
_SECTOR_SCALE = {
    "半導體業": 1.0e10,
    "其他電子業": 2.0e10,
    "電子零組件業": 5.0e9,
    "光電業": 3.0e9,
    "通信網路業": 1.5e10,
    "塑膠工業": 8.0e9,
    "食品工業": 4.0e9,
    "鋼鐵工業": 6.0e9,
    "航運業": 7.0e9,
    "未分類": 2.0e9,
}

# 展示用：對特定股票刻意製造的變動（只影響最後一期 / 最近四季）
_ANOMALY_SCRIPT = {
    "2330.TW": {"rev_yoy_spike": 1.00},   # 月營收年增 +100%（同業平穩 → scope=company）
    "2317.TW": {"ar_mult": 1.80},         # 最近一季應收帳款暴增
    "2308.TW": {"inv_mult": 1.55},        # 最近一季存貨暴增
    "2454.TW": {"gm_last": 0.20},         # 最近一季毛利率由 ~30% 掉到 20%
    "3008.TW": {"accrual": True},         # 最近四季營業現金流轉負（帳面獲利未收現）
}

_ORIGIN_NAME = {
    "revenue": "營業收入合計",
    "gross_profit": "營業毛利（毛損）淨額",
    "net_income": "本期淨利（淨損）",
    "cfo": "營業活動之淨現金流入（流出）",
    "accounts_receivable": "應收帳款淨額",
    "inventory": "存貨",
    "total_assets": "資產總計",
}


def _seed(symbol: str) -> int:
    return int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16) % (2**32)


def _sector_of(symbol: str) -> str:
    info = catalog_info(symbol)
    return info["sector"] if info else "未分類"


def _last_completed_month() -> pd.Period:
    """最近一個已結束的月份（月營收為前月資料）。"""
    return pd.Period(pd.Timestamp.today(), freq="M") - 1


def _last_completed_quarter() -> pd.Period:
    return pd.Period(pd.Timestamp.today(), freq="Q") - 1


class SyntheticFundamentalsSource:
    def get_monthly_revenue(self, symbol: str) -> list[dict]:
        if _sector_of(symbol) in _SKIP_SECTORS:
            return []
        rng = np.random.default_rng(_seed(symbol) ^ 0xA11)
        scale = _SECTOR_SCALE.get(_sector_of(symbol), _SECTOR_SCALE["未分類"])
        periods = pd.period_range(end=_last_completed_month(), periods=_N_MONTHS, freq="M")
        t = np.arange(_N_MONTHS)
        # 平穩年成長約 5% + 溫和季節性 + 小雜訊（雜訊夠小，一般公司不會觸發規則）
        seasonal = 1 + 0.05 * np.sin(2 * np.pi * (periods.month.to_numpy() - 1) / 12)
        rev = scale * (1.05 ** (t / 12)) * seasonal * (1 + rng.normal(0, 0.015, _N_MONTHS))

        script = _ANOMALY_SCRIPT.get(symbol, {})
        if "rev_yoy_spike" in script:
            rev[-1] = rev[-13] * (1 + script["rev_yoy_spike"])

        return [
            {"revenue_year": int(p.year), "revenue_month": int(p.month),
             "revenue": float(round(r))}
            for p, r in zip(periods, rev)
        ]

    def get_statement_items(self, symbol: str) -> list[dict]:
        if _sector_of(symbol) in _SKIP_SECTORS:
            return []
        rng = np.random.default_rng(_seed(symbol) ^ 0xB22)
        scale = _SECTOR_SCALE.get(_sector_of(symbol), _SECTOR_SCALE["未分類"]) * 3.0  # 季 ≈ 3 個月
        q = pd.period_range(end=_last_completed_quarter(), periods=_N_QUARTERS, freq="Q")
        t = np.arange(_N_QUARTERS)

        rev = scale * (1.05 ** (t / 4)) * (1 + rng.normal(0, 0.015, _N_QUARTERS))
        gm = 0.30 + rng.normal(0, 0.004, _N_QUARTERS)
        gp = rev * gm
        ni = rev * 0.10
        ar = rev * 0.50 * (1 + rng.normal(0, 0.01, _N_QUARTERS))
        inv = rev * 0.40 * (1 + rng.normal(0, 0.01, _N_QUARTERS))
        ta = scale * 3.0 * (1.05 ** (t / 4))                 # 總資產平滑成長（時點數）
        cfo_q = ni.copy()                                    # 正常：營業現金流 ≈ 稅後淨利

        script = _ANOMALY_SCRIPT.get(symbol, {})
        if "gm_last" in script:
            gp[-1] = rev[-1] * script["gm_last"]
        if "ar_mult" in script:
            ar[-1] *= script["ar_mult"]
        if "inv_mult" in script:
            inv[-1] *= script["inv_mult"]
        if script.get("accrual"):
            cfo_q[-4:] = -ni[-4:]                             # 最近四季現金流轉負

        # CF 以累計數（YTD）回傳，交給 fundamentals_service 轉單季（SPEC-anomaly §6.7）
        cfo_ytd = pd.Series(cfo_q, index=q).groupby(q.year).cumsum().to_numpy()

        rows: list[dict] = []
        for i, p in enumerate(q):
            period_end = p.to_timestamp(how="end").date().isoformat()
            vals = {
                ("IS", "revenue"): rev[i],
                ("IS", "gross_profit"): gp[i],
                ("IS", "net_income"): ni[i],
                ("BS", "accounts_receivable"): ar[i],
                ("BS", "inventory"): inv[i],
                ("BS", "total_assets"): ta[i],
                ("CF", "cfo"): cfo_ytd[i],
            }
            for (statement, item_type), value in vals.items():
                rows.append({
                    "period_end": period_end,
                    "statement": statement,
                    "item_type": item_type,
                    "origin_name": _ORIGIN_NAME[item_type],
                    "value": float(round(value, 2)),
                })
        return rows
