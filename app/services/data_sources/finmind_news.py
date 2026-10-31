# finmind_news.py
# 真實 TaiwanStockNews（SPEC-anomaly §5.1 / A-04）。
# A-04 實測（2026-10-30）：此 token 可取得新聞，欄位為 date/stock_id/link/source/title，
#   **無 description**（故 RAG 以標題為檢索/引用內容，見 D-A14）；一次只能抓一檔一天（end_date 不可帶）。
from __future__ import annotations

import time
from datetime import date

import requests

_API = "https://api.finmindtrade.com/api/v4/data"
_DATASET = "TaiwanStockNews"
_MAX_RETRY = 3


class FinMindNewsAuthError(RuntimeError):
    pass


class FinMindNewsSource:
    def __init__(self, token: str):
        if not token:
            raise ValueError("FinMind 新聞來源需要 FINMIND_TOKEN。")
        self._token = token

    def fetch_day(self, symbol: str, day: date) -> list[dict]:
        from ...config import settings

        fid = symbol.split(".")[0]
        last_err = None
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                time.sleep(settings.NEWS_THROTTLE_SEC)
                r = requests.get(_API, params={"dataset": _DATASET, "data_id": fid,
                                               "start_date": day.isoformat(),
                                               "token": self._token}, timeout=30)
                if r.status_code == 402:
                    raise RuntimeError(f"FinMind 額度（402）：{r.text[:120]}")
                if r.status_code != 200:
                    raise FinMindNewsAuthError(f"FinMind 新聞 HTTP {r.status_code}：{r.text[:120]}")
                data = r.json().get("data", [])
                out = []
                for d in data:
                    out.append({
                        "published_at": str(d.get("date")),
                        "title": str(d.get("title", "")).strip(),
                        "link": str(d.get("link", "")),
                        "source": d.get("source"),
                        "description": d.get("description"),  # 本版本通常為 None/空
                    })
                return out
            except FinMindNewsAuthError:
                raise
            except (requests.RequestException, RuntimeError) as exc:
                last_err = exc
                time.sleep(settings.NEWS_THROTTLE_SEC * attempt)
        raise RuntimeError(f"FinMind 新聞請求連續失敗：{last_err}")
