# chips_base.py
# 籌碼面資料來源介面（法人買賣超、融資融券）。與股價/財報來源相同的設計——
# 未來換真實來源只改這一層。synthetic 為離線展示用，finmind 需 token。
#
# 兩個方法都回傳「每日一筆、依日期升冪」的 list[dict]，單位與欄位固定，
# 由 chips_engine 做近 N 日彙總；無資料回傳空 list。
from __future__ import annotations

from datetime import date
from typing import Protocol


class ChipsSource(Protocol):
    def get_institutional(self, symbol: str, start: date, end: date) -> list[dict]:
        """三大法人買賣超：每日 {'date':'YYYY-MM-DD','foreign':淨股數,'trust':淨股數,'dealer':淨股數}。
        值為「買進股數 − 賣出股數」（可負）。非個股（ETF 等）或查無資料回傳空 list。"""
        ...

    def get_margin(self, symbol: str, start: date, end: date) -> list[dict]:
        """融資融券餘額：每日 {'date':'YYYY-MM-DD','margin_lots':融資餘額(張),'short_lots':融券餘額(張)}。
        查無資料回傳空 list。"""
        ...


def get_chips_source() -> ChipsSource:
    """依設定回傳對應的籌碼資料來源實作。"""
    from ...config import settings

    if settings.CHIPS_SOURCE == "finmind":
        from .finmind_chips import FinMindChipsSource

        return FinMindChipsSource(settings.FINMIND_TOKEN)
    from .synthetic_chips import SyntheticChipsSource

    return SyntheticChipsSource()
