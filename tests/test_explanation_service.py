# 測試 RAG 解讀的組裝 / 驗證 / 重試 / 備援邏輯（不碰網路，注入假 LLM）。
import pytest

from app.services import explanation_service as es
from app.services.llm_client import LLMUnavailable

FLAG = {
    "symbol": "2330.TW", "rule_id": "R-REV-YOY", "period": "2026-09",
    "value": 1.0, "baseline": 0.05, "z": 8.0, "severity": "極端", "direction": "up",
    "evidence": {"scope": "company", "n_hist": 24, "peer_median_yoy": 0.05},
}
NEWS = [
    {"id": 11, "title": "台積電單月營收年增逾一倍，AI 急單拉貨", "link": "https://x/1",
     "source": "財經", "published_at": "2026-10-08 01:00:00"},
    {"id": 12, "title": "台積電法說會前法人調整評等", "link": "https://x/2",
     "source": "財經", "published_at": "2026-10-09 01:00:00"},
]

GOOD = """## 發生什麼
2026-09 單月營收年增 100%，主要是公司自身變化。
## 可能原因
- 取得大客戶 AI 急單拉貨 [1]
- （推測）去年同期基期偏低
## 需要留意
- 下月營收是否延續
## 資料來源
[1] 台積電單月營收年增逾一倍
## 重要提醒
本內容僅為依公開財報數字計算的變動說明，不構成投資建議，也不代表對公司經營或誠信的判斷。"""

BAD_UNCITED = GOOD.replace("- 取得大客戶 AI 急單拉貨 [1]", "- 取得大客戶 AI 急單拉貨")
BAD_BANNED = GOOD.replace("- （推測）去年同期基期偏低", "- 建議買進 [1]")


def test_good_passes_as_llm():
    out = es.build_explanation(FLAG, "台積電", "半導體業", NEWS,
                               lambda s, u: GOOD)
    assert out["source"] == "llm"
    assert out["cited_news_ids"] == [11, 12]


def test_retry_then_succeed():
    calls = []
    def fake(s, u):
        calls.append(u)
        return BAD_UNCITED if len(calls) == 1 else GOOD
    out = es.build_explanation(FLAG, "台積電", "半導體業", NEWS, fake)
    assert out["source"] == "llm" and len(calls) == 2


def test_banned_word_falls_back():
    out = es.build_explanation(FLAG, "台積電", "半導體業", NEWS, lambda s, u: BAD_BANNED)
    assert out["source"] == "fallback"
    assert "不構成投資建議" in out["text"]


def test_persistently_bad_falls_back():
    out = es.build_explanation(FLAG, "台積電", "半導體業", NEWS, lambda s, u: BAD_UNCITED)
    assert out["source"] == "fallback"


def test_no_news_falls_back():
    out = es.build_explanation(FLAG, "台積電", "半導體業", [], lambda s, u: GOOD)
    assert out["source"] == "fallback" and out["cited_news_ids"] == []


def test_llm_unavailable_falls_back():
    def boom(s, u):
        raise LLMUnavailable("no key")
    out = es.build_explanation(FLAG, "台積電", "半導體業", NEWS, boom)
    assert out["source"] == "fallback"


def test_query_text_direction():
    assert "大增" in es._query_text(FLAG, "台積電")
    down = {**FLAG, "direction": "down"}
    assert "大減" in es._query_text(down, "台積電")
