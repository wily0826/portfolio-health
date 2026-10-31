# 測試評估實驗的拆解與分類（純函式，不碰網路/DB）。
from app.services import eval_service as ev

RAG_TEXT = """## 發生什麼
營收大增。
## 可能原因
- 取得大客戶訂單 [1]
- 新產品放量 [2]
- （推測）去年同期基期偏低
## 需要留意
- 下月營收"""

NORAG_TEXT = """## 發生什麼
營收大增。
## 可能原因
- 可能是接到大單
- 可能是產業景氣復甦
- 應該是新產品熱賣
## 需要留意
- 觀察後續"""


def test_extract_causes():
    assert ev.extract_causes(RAG_TEXT) == [
        "取得大客戶訂單 [1]", "新產品放量 [2]", "（推測）去年同期基期偏低"]


def test_classify_claim():
    assert ev.classify_claim("取得大客戶訂單 [1]") == ev.LABEL_CITED
    assert ev.classify_claim("（推測）基期偏低") == ev.LABEL_SPEC
    assert ev.classify_claim("可能是接到大單") == ev.LABEL_UNSUPPORTED


def test_unsupported_stats_rag_low():
    st = ev.unsupported_stats(ev.extract_causes(RAG_TEXT))
    # 3 點：2 附來源 + 1 推測 → 非推測 2 點全部附來源 → 無根據比例 0
    assert st["n_claims"] == 3 and st["n_speculation"] == 1
    assert st["n_cited"] == 2 and st["n_unsupported"] == 0
    assert st["unsupported_ratio"] == 0.0


def test_unsupported_stats_norag_high():
    st = ev.unsupported_stats(ev.extract_causes(NORAG_TEXT))
    # 3 點全部無來源、無推測 → 無根據比例 100%
    assert st["n_claims"] == 3 and st["n_nonspec"] == 3
    assert st["n_unsupported"] == 3 and st["unsupported_ratio"] == 1.0


def test_empty_causes():
    assert ev.extract_causes("## 發生什麼\n沒有原因段落") == []
    st = ev.unsupported_stats([])
    assert st["unsupported_ratio"] == 0.0 and st["n_claims"] == 0
