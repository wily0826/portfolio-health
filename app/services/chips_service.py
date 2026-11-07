# chips_service.py
# 籌碼面服務層：資料來源（synthetic / finmind）→ chips_engine 彙總 → 摘要 list。
# 籌碼面是「可選關注面向」，只在使用者選到時被呼叫，且只處理其持股；不落 DB。
# 取得失敗（額度/網路/查無）不應讓健檢失敗，故逐檔容錯。
from __future__ import annotations

from datetime import date, timedelta

from ..config import settings
from .chips_engine import summarize_chips
from .data_sources.chips_base import get_chips_source

# 回看日曆天數要比「交易日視窗」寬，才能湊滿 window_days 個交易日（約 1.6 倍 + 緩衝）
_CALENDAR_SPAN_DAYS = 40


def summarize_for(symbols: list[str], window_days: int | None = None) -> list[dict]:
    """回傳各股票的籌碼摘要（可 JSON 序列化）。無資料的股票仍回一筆（欄位為 None）。"""
    window = window_days or settings.CHIP_WINDOW_DAYS
    source = get_chips_source()
    end = date.today()
    start = end - timedelta(days=max(_CALENDAR_SPAN_DAYS, window * 2))

    out = []
    for sym in symbols:
        try:
            inst = source.get_institutional(sym, start, end)
            margin = source.get_margin(sym, start, end)
            out.append(summarize_chips(sym, inst, margin, window_days=window))
        except Exception:  # noqa: BLE001 — 單檔失敗不影響其他檔與整體健檢
            out.append(summarize_chips(sym, [], [], window_days=window))
    return out
