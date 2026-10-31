# news_base.py
# 新聞資料來源介面（SPEC-anomaly §5.1 / §10）：synthetic 離線展示用、finmind 為真實 TaiwanStockNews。
# TaiwanStockNews 一次只能抓「一檔、一天」，且本 token 版本只回 title（無 description，見 D-A14）。
from __future__ import annotations

from datetime import date
from typing import Protocol


class NewsSource(Protocol):
    def fetch_day(self, symbol: str, day: date) -> list[dict]:
        """回傳某一天某檔的新聞列，每筆：
          {'published_at': 'YYYY-MM-DD HH:MM:SS', 'title': str,
           'link': str, 'source': str|None, 'description': str|None}
        無資料回傳空 list。"""
        ...


def get_news_source() -> NewsSource:
    from ...config import settings

    if settings.NEWS_SOURCE == "finmind":
        from .finmind_news import FinMindNewsSource

        return FinMindNewsSource(settings.FINMIND_TOKEN)
    from .synthetic_news import SyntheticNewsSource

    return SyntheticNewsSource()
