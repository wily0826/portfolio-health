# finmind_fundamentals.py
# 真實 FinMind 財報資料源（SPEC-anomaly §5.1 / §5.4）。
#
# ✅ A-02 已完成（2026-10-30，`scripts/verify_finmind_fundamentals.py` 實測）：
#    下方 ITEM_MAP 的 type 以 2330/2317/6488（上櫃）實際回傳確認；三家 type 名稱一致、上櫃資料完整。
#    驗證結論（詳見 SPEC-anomaly §5.4 / §17）：
#      - 損益表（IS）為「單季」值（Q1~Q4 各季獨立，Q4≈Q3 而非 4×）→ 直接使用，不需轉換。
#      - 現金流量表（CF）為「累計數（YTD）」（Q2≈Q1+Q2、跨年重置）→ CFO_IS_CUMULATIVE=True；
#        依既有不變量，fin_statement_items 存入原始 YTD 值，由 fundamentals_service 轉單季。
#      - 資產負債表（BS）同一科目有「絕對值」與「_per（占比）」兩版，取絕對值版。
#    注意：應收帳款僅取 AccountsReceivableNet（不含關係人 AccountsReceivableDuefromRelatedPartiesNet）。
from __future__ import annotations

import time
from datetime import date, timedelta

import requests

_API = "https://api.finmindtrade.com/api/v4/data"
_THROTTLE_SEC = 6.5   # SPEC-anomaly §9.1：≥6.5 秒/次（約 550 次/小時，保留餘裕）
_MAX_RETRY = 3
_BACKFILL_YEARS = 6   # 回補年數：季報年比基準需 ~4 年、月營收年比基準需 ~3 年，取 6 年保留餘裕


def _start_date() -> str:
    return (date.today() - timedelta(days=365 * _BACKFILL_YEARS + 15)).isoformat()

# 鍵 = 引擎標準欄位名；值 = (statement, FinMind 的 type)。以 A-02 實測回傳為準。
ITEM_MAP: dict[str, tuple[str, str]] = {
    "revenue":             ("IS", "Revenue"),                             # 營業收入（單季）
    "gross_profit":        ("IS", "GrossProfit"),                         # 營業毛利（毛損）（單季）
    "net_income":          ("IS", "IncomeAfterTaxes"),                    # 本期淨利（淨損）（單季）
    "cfo":                 ("CF", "NetCashInflowFromOperatingActivities"),# 營業活動之淨現金流入（YTD 累計）
    "accounts_receivable": ("BS", "AccountsReceivableNet"),              # 應收帳款淨額
    "inventory":           ("BS", "Inventories"),                         # 存貨
    "total_assets":        ("BS", "TotalAssets"),                         # 資產總額
}
CFO_IS_CUMULATIVE: bool = True  # A-02 實測：CF 為 YTD 累計數

_DATASET = {
    "revenue": "TaiwanStockMonthRevenue",
    "IS": "TaiwanStockFinancialStatements",
    "BS": "TaiwanStockBalanceSheet",
    "CF": "TaiwanStockCashFlowsStatement",
}


class FinMindFundamentalsAuthError(RuntimeError):
    """權限或額度問題（付費方案、token 無效、額度用完）——重試無益。"""


def _a02_done() -> bool:
    return (CFO_IS_CUMULATIVE is not None
            and all(t != "TODO" for _, t in ITEM_MAP.values()))


class FinMindFundamentalsSource:
    def __init__(self, token: str):
        if not token:
            raise ValueError("FinMind 財報來源需要 FINMIND_TOKEN，請於 .env 設定。")
        self._token = token

    @staticmethod
    def _to_finmind_id(symbol: str) -> str:
        return symbol.split(".")[0]

    def _request(self, params: dict) -> list[dict]:
        last_err: Exception | None = None
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                time.sleep(_THROTTLE_SEC)
                resp = requests.get(_API, params={**params, "token": self._token}, timeout=30)
                if resp.status_code == 402:  # 多為每小時額度上限 → 可重試
                    raise RuntimeError(f"FinMind 額度/限制（402）：{resp.text[:160]}")
                if resp.status_code != 200:
                    raise FinMindFundamentalsAuthError(
                        f"FinMind 拒絕（HTTP {resp.status_code}）：{resp.text[:160]}")
                body = resp.json()
                if body.get("status") != 200:
                    raise FinMindFundamentalsAuthError(f"FinMind 回應異常：{body.get('msg')}")
                return body.get("data", [])
            except FinMindFundamentalsAuthError:
                raise
            except (requests.RequestException, RuntimeError) as exc:
                last_err = exc
                time.sleep(_THROTTLE_SEC * attempt)
        raise RuntimeError(f"FinMind 請求連續失敗：{last_err}")

    def get_monthly_revenue(self, symbol: str) -> list[dict]:
        data = self._request({"dataset": _DATASET["revenue"],
                              "data_id": self._to_finmind_id(symbol),
                              "start_date": _start_date()})
        rows = []
        for d in data:
            try:
                rows.append({
                    "revenue_year": int(d["revenue_year"]),
                    "revenue_month": int(d["revenue_month"]),
                    "revenue": float(d["revenue"]),
                })
            except (KeyError, TypeError, ValueError):
                continue  # 單筆欄位異常不中斷整批
        return rows

    def get_statement_items(self, symbol: str) -> list[dict]:
        if not _a02_done():
            raise NotImplementedError(
                "FinMind 財報三表尚未可用：請先完成 SPEC-anomaly A-02（填好 ITEM_MAP 的 type 與 "
                "CFO_IS_CUMULATIVE），再啟用 FUNDAMENTALS_SOURCE=finmind 的季報偵測。"
                "月營收偵測不受此限。")

        # 反向對照：FinMind type → (statement, 引擎標準欄位名)
        by_type = {(stmt, t): (stmt, std) for std, (stmt, t) in ITEM_MAP.items()}
        rows: list[dict] = []
        for statement in ("IS", "BS", "CF"):
            data = self._request({"dataset": _DATASET[statement],
                                  "data_id": self._to_finmind_id(symbol),
                                  "start_date": _start_date()})
            for d in data:
                key = (statement, d.get("type"))
                if key not in by_type:
                    continue
                _, std_name = by_type[key]
                rows.append({
                    "period_end": str(d.get("date")),
                    "statement": statement,
                    "item_type": std_name,
                    "origin_name": d.get("origin_name"),
                    "value": (float(d["value"]) if d.get("value") is not None else None),
                })
        return rows
