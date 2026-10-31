# synthetic_news.py
# 離線合成新聞（展示 / 測試用）：依 symbol 產生「可重現」且與展示旗標相關的標題，
# 讓 RAG 解讀在沒有 token、沒有網路時也能示範「附引用、可驗證」的流程（SPEC-anomaly §10）。
#
# 注意：這些是為展示而生成的虛構標題，簡報時必須說明。真實新聞請用 NEWS_SOURCE=finmind。
from __future__ import annotations

import hashlib
from datetime import date

from .synthetic import catalog_info

# 與 synthetic_fundamentals 的展示腳本對應的「相關」標題池（讓檢索能命中、引用有意義）
_THEMED: dict[str, list[str]] = {
    "2330.TW": [
        "台積電單月營收年增逾一倍，法人：AI 與先進製程急單強勁拉貨",
        "台積電營收創同期新高，大客戶拉貨挹注動能",
        "外資調升台積電出貨預估，看好營收成長延續",
    ],
    "2317.TW": [
        "鴻海應收帳款走高，法人關注季末集中出貨與收款天數",
        "鴻海大客戶新機備貨，營收與應收帳款同步攀升",
    ],
    "2308.TW": [
        "台達電為新產品與旺季提前備貨，存貨水位明顯上升",
        "台達電庫存增加，法人：反映電源與散熱需求展望",
    ],
    "2454.TW": [
        "聯發科毛利率下滑，產品組合調整與匯率因素；法說會說明",
        "聯發科新產品放量初期，稀釋單季毛利率",
    ],
    "3008.TW": [
        "大立光帳面獲利與營業現金流出現落差，法人關注收現",
        "大立光應收與存貨增加，占用營運現金",
    ],
}

_GENERIC = [
    "{name}股價隨大盤波動，成交量放大",
    "{name}法說會前夕，法人調整評等與預估",
    "{name}獲投信買超，帶動盤面買氣",
]

_SOURCE = "展示新聞（合成）"


def _name(symbol: str) -> str:
    info = catalog_info(symbol)
    return info["name"] if info else symbol


def _link(symbol: str, title: str) -> str:
    h = hashlib.md5(f"{symbol}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"https://demo.local/news/{h}"


class SyntheticNewsSource:
    def fetch_day(self, symbol: str, day: date) -> list[dict]:
        name = _name(symbol)
        themed = _THEMED.get(symbol, [])
        # 每天輪流放一則相關標題 + 一則通用標題；跨多天累積後，相同標題會以 link 去重。
        items: list[str] = []
        if themed:
            items.append(themed[day.toordinal() % len(themed)])
        items.append(_GENERIC[day.toordinal() % len(_GENERIC)].format(name=name))
        out = []
        for i, title in enumerate(items):
            out.append({
                "published_at": f"{day.isoformat()} 0{i}:00:00",
                "title": title,
                "link": _link(symbol, title),
                "source": _SOURCE,
                "description": None,
            })
        return out
