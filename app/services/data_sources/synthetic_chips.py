# synthetic_chips.py
# 離線合成籌碼資料源（展示 / 測試用）：依 symbol 產生「可重現」的法人買賣超與融資融券，
# 讓籌碼面在沒有 FinMind token、沒有網路時也能完整端到端展示。
#
# 注意：這不是真實籌碼，簡報時必須說明。真實資料請用 CHIPS_SOURCE=finmind（需 token）。
#
# 為了讓展示看得到不同籌碼型態，對少數「展示股」刻意製造方向（外資連買 / 投信連賣 / 融券增加）；
# 其餘股票維持小幅隨機進出，方向多半為「持平」。
from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np

# 展示腳本：對特定股票給定明顯的籌碼傾向（net_bias 單位為「張/日」量級，正=買超）
_CHIP_SCRIPT = {
    "2330.TW": {"foreign": 800, "trust": 120, "margin_trend": -40, "short_trend": -5},   # 外資連買、融資降
    "2317.TW": {"foreign": -500, "trust": -60, "margin_trend": 60, "short_trend": 30},   # 外資賣、散戶融資進場、融券增
    "2454.TW": {"foreign": 350, "trust": 200, "margin_trend": 10, "short_trend": 2},
    "2412.TW": {"foreign": -120, "trust": 20, "margin_trend": -5, "short_trend": -1},
}
_DEFAULT = {"foreign": 0, "trust": 0, "margin_trend": 0, "short_trend": 0}


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode("utf-8")).hexdigest(), 16) % (2**32)


def _trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:  # 僅工作日（忽略國定假日，展示足夠）
            days.append(d)
        d += timedelta(days=1)
    return days


class SyntheticChipsSource:
    def _script(self, symbol: str) -> dict:
        return _CHIP_SCRIPT.get(symbol, _DEFAULT)

    def get_institutional(self, symbol: str, start: date, end: date) -> list[dict]:
        rng = np.random.default_rng(_seed(symbol))
        sc = self._script(symbol)
        rows = []
        for d in _trading_days(start, end):
            # 日波動以「張」為量級，再乘 1000 轉股數；加上展示腳本的方向偏移
            foreign = (rng.normal(sc["foreign"], 400) * 1000)
            trust = (rng.normal(sc["trust"], 120) * 1000)
            dealer = (rng.normal(0, 60) * 1000)
            rows.append({
                "date": d.isoformat(),
                "foreign": round(float(foreign)),
                "trust": round(float(trust)),
                "dealer": round(float(dealer)),
            })
        return rows

    def get_margin(self, symbol: str, start: date, end: date) -> list[dict]:
        rng = np.random.default_rng(_seed(symbol) ^ 0x9E3779B9)
        sc = self._script(symbol)
        days = _trading_days(start, end)
        # 從一個依 symbol 決定的基準餘額開始，逐日累加趨勢 + 小幅雜訊
        margin = 20000 + _seed(symbol) % 30000
        short = 1000 + _seed(symbol) % 4000
        rows = []
        for d in days:
            margin = max(0.0, margin + sc["margin_trend"] + float(rng.normal(0, 15)))
            short = max(0.0, short + sc["short_trend"] + float(rng.normal(0, 8)))
            rows.append({
                "date": d.isoformat(),
                "margin_lots": round(margin, 1),
                "short_lots": round(short, 1),
            })
        return rows
