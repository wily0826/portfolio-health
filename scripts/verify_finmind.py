# verify_finmind.py — T-03：FinMind 資料來源驗證
# 用真實 token 測三個資料集，確認「資料集名稱、欄位、請求限制」（SPEC §7.2）。
# 用法：先在 .env 設定 FINMIND_TOKEN，然後：
#   python -m scripts.verify_finmind [股票代號，預設 2330]
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import requests

from app.config import settings

_API = "https://api.finmindtrade.com/api/v4/data"


def _fetch(dataset: str, data_id: str | None = None, days: int = 40) -> tuple[int, str, list]:
    """回傳 (http_status, msg, data)。"""
    params = {"dataset": dataset, "token": settings.FINMIND_TOKEN}
    if data_id:
        params["data_id"] = data_id
        params["start_date"] = (date.today() - timedelta(days=days)).isoformat()
        params["end_date"] = date.today().isoformat()
    time.sleep(1.0)
    r = requests.get(_API, params=params, timeout=25)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text[:160], []
    return r.status_code, str(body.get("msg", "")), body.get("data", [])


def _sep(t: str) -> None:
    print("\n" + "=" * 56 + f"\n{t}\n" + "=" * 56)


def main(argv: list[str]) -> int:
    stock = (argv[0] if argv else "2330").split(".")[0]

    _sep("設定")
    print(f"FINMIND_TOKEN         = {'已設定' if settings.FINMIND_TOKEN else '未設定'}")
    print(f"FINMIND_PRICE_DATASET = {settings.FINMIND_PRICE_DATASET}")
    if not settings.FINMIND_TOKEN:
        print("\n⚠️ 請先在 .env 設定 FINMIND_TOKEN 後再執行。")
        return 1

    results = {}

    # 1) 基本資料（含產業別）
    _sep("① TaiwanStockInfo（基本資料 / 產業別）")
    status, msg, data = _fetch("TaiwanStockInfo")
    if status == 200 and data:
        import pandas as pd
        df = pd.DataFrame(data)
        row = df[df["stock_id"] == stock]
        print(f"HTTP {status}，共 {len(df)} 檔；欄位：{list(df.columns)}")
        if not row.empty:
            r = row.iloc[0]
            print(f"  {stock} = {r.get('stock_name')} / 產業 {r.get('industry_category')} / type {r.get('type')}")
        results["info"] = "OK"
    else:
        print(f"HTTP {status}：{msg}")
        results["info"] = f"FAIL({status})"

    # 2) 還原股價（需付費方案）
    _sep("② TaiwanStockPriceAdj（還原價，需付費方案）")
    status, msg, data = _fetch("TaiwanStockPriceAdj", stock)
    if status == 200 and data:
        import pandas as pd
        df = pd.DataFrame(data)
        print(f"HTTP {status}，{len(df)} 筆；欄位：{list(df.columns)}")
        print(f"  最後一筆：{df.iloc[-1][['date','close']].to_dict()}")
        results["adj"] = "OK"
    else:
        print(f"HTTP {status}：{msg or '(無資料，通常代表權限不足)'}")
        results["adj"] = f"FAIL({status})"

    # 3) 未還原股價（免費可用，比較用）
    _sep("③ TaiwanStockPrice（未還原，免費可用）")
    status, msg, data = _fetch("TaiwanStockPrice", stock)
    if status == 200 and data:
        import pandas as pd
        df = pd.DataFrame(data)
        print(f"HTTP {status}，{len(df)} 筆；欄位：{list(df.columns)}")
        print(f"  最後一筆：{df.iloc[-1][['date','close']].to_dict()}")
        results["raw"] = "OK"
    else:
        print(f"HTTP {status}：{msg}")
        results["raw"] = f"FAIL({status})"

    # 判定
    _sep("判定")
    print(f"基本資料 {results.get('info')} / 還原價 {results.get('adj')} / 未還原價 {results.get('raw')}")
    if results.get("adj") == "OK":
        print("✅ token 可取得還原價 → 直接用 TaiwanStockPriceAdj（符合 D-008）。")
        verdict = 0
    elif results.get("raw") == "OK":
        print("⚠️ token 無還原價權限（免費方案）。選項：")
        print("   a) 升級 FinMind 付費方案以取得 TaiwanStockPriceAdj；或")
        print("   b) 開發期暫設 FINMIND_PRICE_DATASET=TaiwanStockPrice（未還原，除息日會失真，正式不可用）；或")
        print("   c) 展示續用 PRICE_SOURCE=synthetic。")
        verdict = 2
    else:
        print("❌ 連基本資料都取不到，請確認 token 是否正確。")
        verdict = 1
    return verdict


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
