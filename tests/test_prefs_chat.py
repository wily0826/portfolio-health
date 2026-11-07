# test_prefs_chat.py — 關注面向偏好 + 依面向組裝的報告 + 對話式 AI（端到端）
# 與 test_api 共用同一組測試環境變數（sqlite / synthetic / LLM none）；用 setdefault 避免覆蓋先載入者。
import os
import tempfile

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("SQLITE_PATH", os.path.join(tempfile.mkdtemp(prefix="pht_pc_"), "t.db"))
os.environ.setdefault("PRICE_SOURCE", "synthetic")
os.environ.setdefault("CHIPS_SOURCE", "synthetic")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import init_db

init_db()


@pytest.fixture
def client():
    return TestClient(app)


def _login(c, email):
    c.post("/api/auth/register", json={"email": email, "password": "pass1234", "display_name": "X"})
    assert c.post("/api/auth/login", json={"email": email, "password": "pass1234"}).status_code == 200


def test_default_focus_is_all_three(client):
    _login(client, "pref_default@example.com")
    body = client.get("/api/prefs").json()
    assert set(body["focus"]) == {"risk", "fundamental", "chips"}
    assert body["all"] == ["risk", "fundamental", "chips"]


def test_set_focus_filters_and_persists(client):
    _login(client, "pref_set@example.com")
    r = client.put("/api/prefs", json={"focus": ["chips", "bogus", "chips"]})
    assert r.status_code == 200
    assert r.json()["focus"] == ["chips"]          # 去重、濾掉非法值
    assert client.get("/api/prefs").json()["focus"] == ["chips"]


def test_empty_focus_falls_back_to_all(client):
    _login(client, "pref_empty@example.com")
    assert client.put("/api/prefs", json={"focus": []}).json()["focus"] == \
        ["risk", "fundamental", "chips"]


def test_report_sections_follow_focus(client):
    _login(client, "focus_report@example.com")
    client.put("/api/prefs", json={"focus": ["chips"]})
    for sym, sh in [("2330.TW", 100), ("2317.TW", 500)]:
        assert client.post("/api/holdings", json={"symbol": sym, "shares": sh}).status_code == 200

    body = client.post("/api/reports").json()
    assert body["focus"] == ["chips"]
    assert body["chip_summary"], "選到籌碼面時應回傳 chip_summary"
    assert "## 籌碼面觀察" in body["ai_report"]
    assert "## 主要風險" not in body["ai_report"]   # 未選風險結構 → 不出該段
    assert "## 總評" in body["ai_report"]           # 總評恆在


def test_chat_requires_report_then_answers(client):
    _login(client, "chat_user@example.com")
    # 沒有報告 → 400
    r0 = client.post("/api/chat", json={"message": "我的風險如何？"})
    assert r0.status_code == 400
    assert r0.json()["error"]["code"] == "NO_REPORT"

    # 先產生報告
    client.post("/api/holdings", json={"symbol": "2330.TW", "shares": 100})
    assert client.post("/api/reports").status_code == 200

    # LLM none → 回備援訊息但仍 200
    r = client.post("/api/chat", json={"message": "哪一項指標讓風險分數偏高？"})
    assert r.status_code == 200
    assert r.json()["source"] in ("unavailable", "fallback", "llm")
    assert r.json()["text"]
