# test_anomaly_service.py — 掃描持久化回歸測試（D-A17）
# 驗證 _persist 以自然鍵 (symbol,rule_id,period) upsert：重跑 scan 時旗標 id 穩定、
# 既有 LLM（RAG）解讀不被規則式備援覆寫。用獨立暫存 SQLite + synthetic 離線資料源。
import os
import tempfile

# 必須在匯入 app 之前設定（config 於匯入時讀取 os.environ）；用 setdefault 不覆蓋
# 其他測試模組或 .env 既有值。SQLITE_PATH 必須指向獨立暫存檔：此模組字母序早於
# test_api，若先 import 會固定 config，漏設 SQLITE_PATH 會讓它落回預設 ./data/app.db
# （開發用 DB），連帶使 test_api 連到帶殘留資料的開發 DB。
os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("SQLITE_PATH",
                      os.path.join(tempfile.mkdtemp(prefix="anom_svc_test_"), "anom.db"))
os.environ.setdefault("PRICE_SOURCE", "synthetic")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest

from app import db as dbmod
from app.config import settings


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "anom.db"))
    monkeypatch.setattr(settings, "PRICE_SOURCE", "synthetic")
    monkeypatch.setattr(settings, "FUNDAMENTALS_SOURCE", "synthetic")
    monkeypatch.setattr(settings, "NEWS_SOURCE", "synthetic")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "none")
    dbmod.init_db()

    from app.services import fundamentals_service as fs
    from app.services.data_sources.synthetic import catalog_info, catalog_symbols

    conn = dbmod.get_conn()
    try:
        for sym in catalog_symbols():
            i = catalog_info(sym)
            conn.execute(
                "INSERT OR REPLACE INTO stocks (symbol, market, name, sector, currency) "
                "VALUES (?, ?, ?, ?, ?)",
                (sym, i["market"], i["name"], i["sector"], "TWD"),
            )
        conn.commit()
    finally:
        conn.close()
    for sym in catalog_symbols():
        fs.backfill_symbol(sym)
    yield


def _id_map() -> dict:
    conn = dbmod.get_conn()
    try:
        return {(r["symbol"], r["rule_id"]): r["id"]
                for r in conn.execute("SELECT id, symbol, rule_id FROM anomalies").fetchall()}
    finally:
        conn.close()


def test_scan_ids_stable_across_runs(seeded):
    from app.services import anomaly_service as asv

    asv.scan()
    first = _id_map()
    assert first, "展示股池應至少偵測到一個旗標"
    asv.scan()
    assert _id_map() == first, "重跑 scan 後旗標 id 不應漂移"


def test_llm_explanation_preserved_on_rescan(seeded):
    from app.services import anomaly_service as asv

    asv.scan()
    target = next(iter(_id_map().values()))
    conn = dbmod.get_conn()
    try:
        conn.execute(
            "UPDATE anomaly_explanations SET explanation = ?, source = 'llm' WHERE anomaly_id = ?",
            ("AI 生成的解讀，引用新聞 [1]", target),
        )
        conn.commit()
    finally:
        conn.close()

    asv.scan()  # 重新掃描不得覆寫既有 LLM 解讀

    conn = dbmod.get_conn()
    try:
        r = conn.execute(
            "SELECT explanation, source FROM anomaly_explanations WHERE anomaly_id = ?",
            (target,),
        ).fetchone()
    finally:
        conn.close()
    assert r["source"] == "llm"
    assert r["explanation"] == "AI 生成的解讀，引用新聞 [1]"
