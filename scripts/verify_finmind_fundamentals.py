# verify_finmind_fundamentals.py — A-02：FinMind 財報三表驗證（SPEC-anomaly §5.2 / §5.4）
# 目的：
#   1. 印出損益表 / 資產負債表 / 現金流量表的所有 type 與 origin_name，供填 ITEM_MAP
#   2. 驗證現金流量是累計數還是單季數（Q2 ≈ 2×Q1 → 累計）
#   3. 驗證損益表營收 Q4 是單季還是全年（Q4 ≈ Q3 → 單季）
#   4. 檢查上櫃公司資料是否完整
# 用法：python -m scripts.verify_finmind_fundamentals
from __future__ import annotations

import time
from collections import defaultdict

import pandas as pd
import requests

from app.config import settings

_API = "https://api.finmindtrade.com/api/v4/data"
_DATASET = {
    "IS": "TaiwanStockFinancialStatements",
    "BS": "TaiwanStockBalanceSheet",
    "CF": "TaiwanStockCashFlowsStatement",
}
_COMPANIES = [("2330", "台積電/上市"), ("2317", "鴻海/上市"), ("6488", "環球晶/上櫃")]
_START = "2022-01-01"
_THROTTLE = 2.5


def _fetch(dataset: str, data_id: str) -> tuple[int, str, list]:
    time.sleep(_THROTTLE)
    r = requests.get(_API, params={"dataset": dataset, "data_id": data_id,
                                   "start_date": _START, "token": settings.FINMIND_TOKEN}, timeout=30)
    try:
        b = r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text[:160], []
    return r.status_code, str(b.get("msg", "")), b.get("data", [])


def _sep(t: str) -> None:
    print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)


def _print_types(stmt: str, data: list) -> None:
    df = pd.DataFrame(data)
    if df.empty:
        print(f"  [{stmt}] 無資料")
        return
    pairs = df[["type", "origin_name"]].drop_duplicates().sort_values("type")
    print(f"  [{stmt}] 期別數={df['date'].nunique()}，type 共 {len(pairs)} 種：")
    for _, r in pairs.iterrows():
        print(f"    - {r['type']:<34} {r['origin_name']}")


def _series(data: list, type_name: str) -> pd.Series:
    df = pd.DataFrame(data)
    sub = df[df["type"] == type_name].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
    return sub.set_index("date")["value"].sort_index()


def main() -> int:
    if not settings.FINMIND_TOKEN:
        print("⚠️ 請先在 .env 設定 FINMIND_TOKEN。")
        return 1

    # 用 2330 列出所有 type/origin_name（填 ITEM_MAP 用）
    _sep("① 2330 三表 type / origin_name（填 ITEM_MAP 用）")
    data2330 = {}
    for stmt, ds in _DATASET.items():
        status, msg, data = _fetch(ds, "2330")
        print(f"\n{ds}（HTTP {status}）{'' if status==200 else msg}")
        data2330[stmt] = data
        _print_types(stmt, data)

    # 現金流量是否累計
    _sep("② 現金流量：累計數 vs 單季數（Q2 ≈ 2×Q1 → 累計）")
    cf = pd.DataFrame(data2330["CF"])
    if not cf.empty:
        # 取出現數最多的候選（通常即營業活動現金流），逐 type 印最近 5 期協助判讀
        cand = [t for t in cf["type"].unique()
                if any(k in str(t) for k in ("Operat", "operat", "OperatingActivities", "CashFlow"))]
        cand = cand or list(cf["type"].unique())[:3]
        for t in cand[:4]:
            s = _series(data2330["CF"], t).tail(6)
            print(f"\n  type={t}")
            for d, v in s.items():
                print(f"    {d}  {v:,.0f}")

    # 損益表營收 Q4 單季 vs 全年
    _sep("③ 損益表營收：Q4 單季 vs 全年（Q4 ≈ Q3 → 單季；≈4×Q3 → 全年）")
    is_df = pd.DataFrame(data2330["IS"])
    if not is_df.empty:
        rev_cand = [t for t in is_df["type"].unique()
                    if any(k in str(t) for k in ("Revenue", "revenue", "OperatingRevenue", "NetSales"))]
        for t in (rev_cand or list(is_df["type"].unique())[:2]):
            s = _series(data2330["IS"], t).tail(8)
            print(f"\n  type={t}")
            for d, v in s.items():
                print(f"    {d}  {v:,.0f}")

    # 上櫃完整性
    _sep("④ 其他公司（含上櫃）完整性")
    for cid, label in _COMPANIES[1:]:
        print(f"\n--- {cid} {label} ---")
        for stmt, ds in _DATASET.items():
            status, msg, data = _fetch(ds, cid)
            n_types = pd.DataFrame(data)["type"].nunique() if data else 0
            n_dates = pd.DataFrame(data)["date"].nunique() if data else 0
            print(f"  {ds}: HTTP {status}, 期別 {n_dates}, type {n_types}")

    print("\n完成。請依 ① 的 type 填 app/services/data_sources/finmind_fundamentals.py 的 ITEM_MAP，"
          "依 ② 設定 CFO_IS_CUMULATIVE，並把結論記進 SPEC-anomaly §17/§5.4。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
