# synthetic.py
# 離線合成資料來源（展示 / 測試用）：不連網路，依 symbol 產生「可重現」的還原價序列。
# 目的：讓整條流程在沒有 FinMind token、沒有網路時也能完整 demo（SPEC §2 展示版）。
# 注意：這不是真實股價，簡報時必須說明。真實資料請用 PRICE_SOURCE=finmind。
from __future__ import annotations

import hashlib
from datetime import date

import numpy as np
import pandas as pd

# 常見台股基本資料（代號 → 名稱、產業、市場）。未收錄者走 _generic()。
_CATALOG: dict[str, dict] = {
    "2330.TW": {"name": "台積電", "sector": "半導體業", "market": "TW"},
    "2317.TW": {"name": "鴻海", "sector": "其他電子業", "market": "TW"},
    "2454.TW": {"name": "聯發科", "sector": "半導體業", "market": "TW"},
    "3711.TW": {"name": "日月光投控", "sector": "半導體業", "market": "TW"},
    # 多補幾檔半導體，讓同業比較有足夠樣本（SPEC-anomaly MIN_PEERS = 5，不含自己）
    "2303.TW": {"name": "聯電", "sector": "半導體業", "market": "TW"},
    "3034.TW": {"name": "聯詠", "sector": "半導體業", "market": "TW"},
    "2379.TW": {"name": "瑞昱", "sector": "半導體業", "market": "TW"},
    "3443.TW": {"name": "創意", "sector": "半導體業", "market": "TW"},
    "3661.TW": {"name": "世芯-KY", "sector": "半導體業", "market": "TW"},
    "2308.TW": {"name": "台達電", "sector": "電子零組件業", "market": "TW"},
    "3008.TW": {"name": "大立光", "sector": "光電業", "market": "TW"},
    "2412.TW": {"name": "中華電", "sector": "通信網路業", "market": "TW"},
    "2881.TW": {"name": "富邦金", "sector": "金融保險業", "market": "TW"},
    "2882.TW": {"name": "國泰金", "sector": "金融保險業", "market": "TW"},
    "2891.TW": {"name": "中信金", "sector": "金融保險業", "market": "TW"},
    "2886.TW": {"name": "兆豐金", "sector": "金融保險業", "market": "TW"},
    "2884.TW": {"name": "玉山金", "sector": "金融保險業", "market": "TW"},
    "1301.TW": {"name": "台塑", "sector": "塑膠工業", "market": "TW"},
    "1303.TW": {"name": "南亞", "sector": "塑膠工業", "market": "TW"},
    "1216.TW": {"name": "統一", "sector": "食品工業", "market": "TW"},
    "2002.TW": {"name": "中鋼", "sector": "鋼鐵工業", "market": "TW"},
    "2603.TW": {"name": "長榮", "sector": "航運業", "market": "TW"},
    "2609.TW": {"name": "陽明", "sector": "航運業", "market": "TW"},
    "0050.TW": {"name": "元大台灣50", "sector": "ETF", "market": "TW"},
    "0056.TW": {"name": "元大高股息", "sector": "ETF", "market": "TW"},
}

# 各產業的年化漂移 / 波動設定，讓合成資料的風險特徵有差異。
_SECTOR_PROFILE = {
    "半導體業": (0.18, 0.32),
    "其他電子業": (0.10, 0.28),
    "電子零組件業": (0.12, 0.27),
    "光電業": (0.08, 0.38),
    "通信網路業": (0.04, 0.14),
    "金融保險業": (0.06, 0.18),
    "塑膠工業": (0.03, 0.20),
    "食品工業": (0.05, 0.15),
    "鋼鐵工業": (0.02, 0.24),
    "航運業": (0.05, 0.45),
    "ETF": (0.08, 0.16),
    "未分類": (0.06, 0.25),
}

_TRADING_DAYS = 252


class SyntheticSource:
    def get_info(self, symbol: str) -> dict:
        info = _CATALOG.get(symbol) or self._generic(symbol)
        return {
            "name": info["name"],
            "sector": info["sector"],
            "currency": "USD" if info["market"] == "US" else "TWD",
            "market": info["market"],
        }

    def get_history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        info = _CATALOG.get(symbol) or self._generic(symbol)
        mu_ann, sigma_ann = _SECTOR_PROFILE.get(info["sector"], _SECTOR_PROFILE["未分類"])
        seed = int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(seed)

        # 只取交易日（週一到週五），忽略國定假日（展示足夠）。
        idx = pd.bdate_range(start=start, end=end)
        if len(idx) == 0:
            return pd.DataFrame(columns=["trade_date", "close"])

        mu_d = mu_ann / _TRADING_DAYS
        sigma_d = sigma_ann / np.sqrt(_TRADING_DAYS)
        rets = rng.normal(mu_d, sigma_d, len(idx))
        base = 20 + (seed % 900)  # 起始價 20~920 之間，依 symbol 固定
        close = base * np.cumprod(1.0 + rets)

        return pd.DataFrame(
            {"trade_date": idx.date, "close": np.round(close, 2)}
        )

    @staticmethod
    def _generic(symbol: str) -> dict:
        is_us = "." not in symbol
        return {
            "name": symbol,
            "sector": "未分類",
            "market": "US" if is_us else "TW",
        }


# --- 供財報合成資料源（synthetic_fundamentals）共用，確保產業分類一致 ---
def catalog_info(symbol: str) -> dict | None:
    """回傳收錄清單中的基本資料；未收錄回傳 None。"""
    return _CATALOG.get(symbol)


def catalog_symbols() -> list[str]:
    """回傳所有收錄的台股代號（排序後，可重現）。"""
    return sorted(_CATALOG.keys())
