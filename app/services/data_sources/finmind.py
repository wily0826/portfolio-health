# finmind.py
# FinMind 台股資料來源（SPEC §7.2）。把 API 細節封裝在此，其他模組不需知道。
#
# T-03 已對照 FinMind 官方技術文件確認（2026-10-11）：
#   - 還原股價資料集：TaiwanStockPriceAdj，欄位 date, stock_id, open, max, min, close, ...
#     （close 即還原收盤價）。⚠️ 此資料集需「付費方案（backer/sponsor）」，免費 token 無法取得。
#   - 一般股價（未還原）：TaiwanStockPrice，欄位相同；免費可用，但除息日會被誤判下跌（違反 D-008）。
#   - 股票基本資料（含產業別）：TaiwanStockInfo，欄位 stock_id, stock_name, industry_category, type。
#   資料集名稱可用 .env 的 FINMIND_PRICE_DATASET 覆寫；免費額度有每小時上限，故已做節流與重試。
from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

from ...config import settings

_API = "https://api.finmindtrade.com/api/v4/data"
_DATASET_INFO = "TaiwanStockInfo"       # 股票基本資料（含 industry_category）
_MAX_RETRY = 3
_THROTTLE_SEC = 1.0  # 每次請求間隔，避免觸發每小時上限


class FinMindAuthError(RuntimeError):
    """權限或額度問題（付費方案、token 無效、額度用完）——重試無益。"""


class FinMindSource:
    def __init__(self, token: str):
        if not token:
            raise ValueError("FinMind 來源需要 FINMIND_TOKEN，請於 .env 設定。")
        self._token = token
        self._info_cache: pd.DataFrame | None = None

    # --- 代號轉換：本系統 2330.TW / 6488.TWO ↔ FinMind 2330 ---
    @staticmethod
    def _to_finmind_id(symbol: str) -> str:
        return symbol.split(".")[0]

    @staticmethod
    def _suffix_for_type(type_: str) -> str:
        # FinMind TaiwanStockInfo 的 type 欄位：twse=上市→.TW，tpex=上櫃→.TWO
        return ".TWO" if str(type_).lower() in ("tpex", "otc") else ".TW"

    def _request(self, params: dict) -> list[dict]:
        last_err: Exception | None = None
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                time.sleep(_THROTTLE_SEC)
                # token 依 FinMind 文件以參數傳遞；全程 HTTPS
                resp = requests.get(_API, params={**params, "token": self._token}, timeout=20)
                # 402：多為每小時額度上限 → 可重試（指數退避）
                if resp.status_code == 402:
                    raise RuntimeError(f"FinMind 額度/限制（402）：{self._safe_msg(resp)}")
                # 400/401/403：權限或參數問題（例：免費方案存取還原價）→ 重試無益
                if resp.status_code != 200:
                    raise FinMindAuthError(
                        f"FinMind 拒絕（HTTP {resp.status_code}）：{self._safe_msg(resp)}"
                    )
                body = resp.json()
                if body.get("status") != 200:
                    raise FinMindAuthError(f"FinMind 回應異常：{body.get('msg')}")
                return body.get("data", [])
            except FinMindAuthError:
                raise  # 權限/額度問題重試無益，直接往上拋
            except (requests.RequestException, RuntimeError) as exc:
                last_err = exc
                time.sleep(_THROTTLE_SEC * attempt * 2)  # 指數退避
        raise RuntimeError(f"FinMind 請求連續失敗：{last_err}")

    @staticmethod
    def _safe_msg(resp: requests.Response) -> str:
        try:
            return str(resp.json().get("msg", resp.text[:160]))
        except Exception:  # noqa: BLE001
            return resp.text[:160]

    def _load_info_table(self) -> pd.DataFrame:
        if self._info_cache is None:
            data = self._request({"dataset": _DATASET_INFO})
            self._info_cache = pd.DataFrame(data)
        return self._info_cache

    def get_info(self, symbol: str) -> dict:
        fid = self._to_finmind_id(symbol)
        table = self._load_info_table()
        rows = table[table["stock_id"] == fid]
        if rows.empty:
            raise LookupError(f"FinMind 查無此股票：{symbol}")
        row = rows.iloc[0]
        return {
            "name": str(row.get("stock_name", symbol)),
            "sector": (str(row["industry_category"])
                       if row.get("industry_category") else None),
            "currency": "TWD",
            "market": "TW",
        }

    def get_history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        fid = self._to_finmind_id(symbol)
        dataset = settings.FINMIND_PRICE_DATASET
        data = self._request({
            "dataset": dataset,
            "data_id": fid,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        })
        if not data:
            return pd.DataFrame(columns=["trade_date", "close"])
        df = pd.DataFrame(data)
        if "close" not in df.columns:
            raise RuntimeError(
                f"FinMind 資料集 {dataset} 未含 close 欄位，實際欄位：{list(df.columns)}"
            )
        df = df.rename(columns={"date": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df[["trade_date", "close"]].sort_values("trade_date").reset_index(drop=True)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        return df.dropna(subset=["close"])
