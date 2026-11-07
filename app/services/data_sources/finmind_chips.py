# finmind_chips.py
# 真實籌碼資料源：FinMind 的三大法人買賣超與融資融券。
# 沿用 finmind.py 的請求/重試/節流機制（組合，不重寫）。
#
# ⚠️ 單位校準（啟用 finmind 前請對照一次實際回傳，比照 CLAUDE.md 第 4 點）：
#   - 法人買賣超 buy/sell：FinMind 以「股」回傳，本層輸出淨股數（engine 會 ÷1000 轉張）。
#   - 融資融券 TodayBalance：本層視為「張」直接輸出；若實際為「股」，於此處 ÷1000。
from __future__ import annotations

from datetime import date

from .finmind import FinMindSource

_DS_INST = "TaiwanStockInstitutionalInvestorsBuySell"
_DS_MARGIN = "TaiwanStockMarginPurchaseShortSale"


def _investor_bucket(name: str) -> str | None:
    """把 FinMind 的法人名稱歸入 foreign / trust / dealer。"""
    n = (name or "").lower()
    if "foreign" in n:
        return "foreign"
    if "trust" in n:          # Investment_Trust 投信
        return "trust"
    if "dealer" in n:         # Dealer_self / Dealer_Hedging 自營商
        return "dealer"
    return None


class FinMindChipsSource:
    def __init__(self, token: str):
        self._fm = FinMindSource(token)  # 重用代號轉換與 _request

    def get_institutional(self, symbol: str, start: date, end: date) -> list[dict]:
        fid = self._fm._to_finmind_id(symbol)
        data = self._fm._request({
            "dataset": _DS_INST, "data_id": fid,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        })
        # 依日期彙總各法人淨買賣超（買-賣，股）
        by_date: dict[str, dict] = {}
        for r in data:
            bucket = _investor_bucket(r.get("name", ""))
            if bucket is None:
                continue
            d = str(r.get("date"))
            net = float(r.get("buy", 0) or 0) - float(r.get("sell", 0) or 0)
            row = by_date.setdefault(d, {"date": d, "foreign": 0.0, "trust": 0.0, "dealer": 0.0})
            row[bucket] += net
        return [by_date[d] for d in sorted(by_date)]

    def get_margin(self, symbol: str, start: date, end: date) -> list[dict]:
        fid = self._fm._to_finmind_id(symbol)
        data = self._fm._request({
            "dataset": _DS_MARGIN, "data_id": fid,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        })
        rows = []
        for r in data:
            rows.append({
                "date": str(r.get("date")),
                "margin_lots": float(r.get("MarginPurchaseTodayBalance", 0) or 0),
                "short_lots": float(r.get("ShortSaleTodayBalance", 0) or 0),
            })
        return sorted(rows, key=lambda x: x["date"])
