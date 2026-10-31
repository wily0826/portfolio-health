# fundamentals_base.py
# 財報資料來源介面（SPEC-anomaly §5）：與股價來源相同的設計——
# 未來換真實授權來源只改這一層。synthetic 為離線展示用，finmind 需 token 且先完成 A-02。
from __future__ import annotations

from typing import Protocol


class FundamentalsSource(Protocol):
    def get_monthly_revenue(self, symbol: str) -> list[dict]:
        """回傳月營收列：每筆 {'revenue_year': int, 'revenue_month': int, 'revenue': float}。
        非營收型標的（ETF、金融保險業）回傳空 list。"""
        ...

    def get_statement_items(self, symbol: str) -> list[dict]:
        """回傳三大報表的長表列，每筆：
          {'period_end': 'YYYY-MM-DD', 'statement': 'IS'|'BS'|'CF',
           'item_type': <引擎標準欄位名>, 'origin_name': str|None, 'value': float|None}
        item_type 已轉為引擎標準欄位（revenue/gross_profit/net_income/cfo/
        accounts_receivable/inventory/total_assets）；科目對照由各來源自行完成。
        CF 的 cfo 以「累計數（YTD）」回傳，由 fundamentals_service 轉單季（SPEC-anomaly §6.7）。
        無資料回傳空 list。"""
        ...


def get_fundamentals_source() -> FundamentalsSource:
    """依設定回傳對應的財報資料來源實作。"""
    from ...config import settings

    if settings.FUNDAMENTALS_SOURCE == "finmind":
        from .finmind_fundamentals import FinMindFundamentalsSource

        return FinMindFundamentalsSource(settings.FINMIND_TOKEN)
    # 預設：離線合成資料（展示用）
    from .synthetic_fundamentals import SyntheticFundamentalsSource

    return SyntheticFundamentalsSource()
