# test_api.py — 端到端 API 測試（流程強化版 §9.2）
# 使用獨立的暫存 SQLite 與 synthetic 資料來源、LLM none（走 fallback）。
import os
import tempfile

# 必須在匯入 app 之前設定環境變數（config 於匯入時讀取）
_TMP = tempfile.mkdtemp(prefix="pht_test_")
os.environ["DB_BACKEND"] = "sqlite"
os.environ["SQLITE_PATH"] = os.path.join(_TMP, "test.db")
os.environ["PRICE_SOURCE"] = "synthetic"
os.environ["LLM_PROVIDER"] = "none"
os.environ["JWT_SECRET"] = "test-secret"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_conn, init_db

# TestClient 未使用 context manager 時不會觸發 lifespan，故此處顯式建表。
init_db()


@pytest.fixture
def client():
    return TestClient(app)


def _register_and_login(c, email, pw="pass1234", name="測試者"):
    c.post("/api/auth/register", json={"email": email, "password": pw, "display_name": name})
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200


def test_register_and_duplicate(client):
    r = client.post("/api/auth/register",
                    json={"email": "a@example.com", "password": "pass1234", "display_name": "A"})
    assert r.status_code == 200
    r2 = client.post("/api/auth/register",
                     json={"email": "a@example.com", "password": "pass1234", "display_name": "A"})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "AUTH_EMAIL_EXISTS"


def test_wrong_password_cannot_login(client):
    client.post("/api/auth/register",
                json={"email": "b@example.com", "password": "pass1234", "display_name": "B"})
    r = client.post("/api/auth/login", json={"email": "b@example.com", "password": "wrong999"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_unauthenticated_cannot_read_holdings(client):
    r = client.get("/api/holdings")
    assert r.status_code == 401


def test_user_isolation(client):
    ca, cb = TestClient(app), TestClient(app)
    _register_and_login(ca, "ua@example.com")
    _register_and_login(cb, "ub@example.com")
    ca.post("/api/holdings", json={"symbol": "2330.TW", "shares": 100})
    assert len(ca.get("/api/holdings").json()["items"]) == 1
    assert len(cb.get("/api/holdings").json()["items"]) == 0  # B 看不到 A 的持股


def test_holdings_crud_and_report_flow(client):
    _register_and_login(client, "flow@example.com")
    # 新增三檔
    for sym, sh in [("2330.TW", 100), ("2412.TW", 2000), ("2881.TW", 3000)]:
        r = client.post("/api/holdings", json={"symbol": sym, "shares": sh})
        assert r.status_code == 200
    items = client.get("/api/holdings").json()["items"]
    assert len(items) == 3
    assert all(h["status"] == "ready" for h in items)

    # 修改與刪除
    hid = items[0]["id"]
    assert client.put(f"/api/holdings/{hid}", json={"shares": 150}).status_code == 200
    r = client.delete(f"/api/holdings/{hid}")
    assert r.status_code == 200

    # 產生報告 → fallback（LLM none）
    r = client.post("/api/reports")
    assert r.status_code == 200
    body = r.json()
    assert body["report_source"] == "fallback"
    assert 0 <= body["risk_score"] <= 100
    assert body["risk_level"] in ("低", "中", "高")
    assert "## 總評" in body["ai_report"]
    assert body["curve"]["dates"] and body["curve"]["values"]

    # 報告有寫入並可重查
    lst = client.get("/api/reports").json()["items"]
    assert len(lst) >= 1
    rid = lst[0]["id"]
    assert client.get(f"/api/reports/{rid}").status_code == 200


def test_no_holdings_cannot_report(client):
    _register_and_login(client, "empty@example.com")
    r = client.post("/api/reports")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "NO_HOLDINGS"


def test_insufficient_data_returns_422(client):
    _register_and_login(client, "insuf@example.com")
    client.post("/api/holdings", json={"symbol": "2330.TW", "shares": 100})
    # 人為刪到只剩 10 筆價格 → 應回 422
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM prices WHERE symbol='2330.TW' AND trade_date NOT IN "
            "(SELECT trade_date FROM prices WHERE symbol='2330.TW' ORDER BY trade_date DESC LIMIT 10)"
        )
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/reports")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_PRICE_DATA"
    assert "2330.TW" in r.json()["error"]["details"]["symbols"]


def test_invalid_symbol_rejected(client):
    _register_and_login(client, "sym@example.com")
    r = client.post("/api/holdings", json={"symbol": "!!bad!!", "shares": 10})
    assert r.status_code == 422  # pydantic pattern 驗證
