# base.py
# 資料來源介面（SPEC §7.1）：未來商用換授權來源只改這一層。
from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd


class PriceSource(Protocol):
    def get_history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """回傳欄位 ['trade_date', 'close']；close 為還原價；依日期遞增。"""
        ...

    def get_info(self, symbol: str) -> dict:
        """回傳 {'name': str, 'sector': str | None, 'currency': str, 'market': 'TW'|'US'}；
        查無此股票拋 LookupError。"""
        ...


def get_source() -> PriceSource:
    """依設定回傳對應的資料來源實作。"""
    from ...config import settings

    if settings.PRICE_SOURCE == "finmind":
        from .finmind import FinMindSource

        return FinMindSource(settings.FINMIND_TOKEN)
    # 預設：離線合成資料（展示用）
    from .synthetic import SyntheticSource

    return SyntheticSource()
