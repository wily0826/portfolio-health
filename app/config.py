# config.py
# 集中讀取環境變數（SPEC §5）。為了讓專題免安裝 MySQL 即可展示，
# DB 預設使用 SQLite；生產目標為 MySQL 8（schema 見 sql/schema.sql）。
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """極簡 .env 讀取器，避免額外相依套件。已存在的環境變數不覆蓋。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


class Settings:
    # 認證
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "72"))
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    # 資料庫（開發/測試：sqlite；生產：mysql）
    DB_BACKEND: str = os.getenv("DB_BACKEND", "sqlite")  # sqlite | mysql
    SQLITE_PATH: str = os.getenv("SQLITE_PATH", str(BASE_DIR / "data" / "app.db"))
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "portfolio_health")
    # 部署用：啟動時若使用者表為空，自動跑 seed_demo 建 demo 帳號與資料（本地預設關閉）
    AUTO_SEED: bool = os.getenv("AUTO_SEED", "false").lower() == "true"

    # 股價資料來源（synthetic 為離線展示用；finmind 需 token）
    PRICE_SOURCE: str = os.getenv("PRICE_SOURCE", "synthetic")  # synthetic | finmind
    # 財報資料來源（SPEC-anomaly §5）。synthetic 為離線展示用，可完整端到端跑；
    # finmind 需 token，且正式啟用前必須先完成 A-02 驗證（填好 ITEM_MAP、確認現金流是否累計）。
    FUNDAMENTALS_SOURCE: str = os.getenv("FUNDAMENTALS_SOURCE", "synthetic")  # synthetic | finmind
    FINMIND_TOKEN: str = os.getenv("FINMIND_TOKEN", "")
    # 還原股價資料集。預設 TaiwanStockPriceAdj（需付費 backer/sponsor 方案）。
    # 免費 token 可暫設 TaiwanStockPrice（未還原）做開發，但除息日會被誤判下跌（違反 D-008），正式不可用。
    FINMIND_PRICE_DATASET: str = os.getenv("FINMIND_PRICE_DATASET", "TaiwanStockPriceAdj")
    BACKFILL_YEARS: int = int(os.getenv("BACKFILL_YEARS", "2"))

    # LLM（無 key 時自動走規則式備援報告）
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "none")  # none | openai | gemini
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))

    # 風險引擎
    RISK_FREE_RATE: float = float(os.getenv("RISK_FREE_RATE", "0.015"))

    # 成本控制
    MAX_REPORTS_PER_DAY: int = int(os.getenv("MAX_REPORTS_PER_DAY", "10"))

    # 財報變動偵測（SPEC-anomaly）：健檢報告「基本面提醒」只看最近幾個月內的旗標
    ANOMALY_ALERT_MONTHS: int = int(os.getenv("ANOMALY_ALERT_MONTHS", "6"))

    # RAG AI 解讀（SPEC-anomaly §10）
    # 新聞來源：synthetic（離線合成，預設，供展示/測試）| finmind（真實 TaiwanStockNews，需 token）
    NEWS_SOURCE: str = os.getenv("NEWS_SOURCE", "synthetic")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "8"))
    # 新聞抓取：一次一檔一天；為了互動式產生解讀的回應時間，時間窗預設較 §9.2 窄（可調）
    NEWS_WINDOW_BEFORE: int = int(os.getenv("NEWS_WINDOW_BEFORE", "14"))
    NEWS_WINDOW_AFTER: int = int(os.getenv("NEWS_WINDOW_AFTER", "3"))
    NEWS_THROTTLE_SEC: float = float(os.getenv("NEWS_THROTTLE_SEC", "1.5"))
    NEWS_MAX_DAYS: int = int(os.getenv("NEWS_MAX_DAYS", "20"))  # 單一旗標最多抓幾天，控成本
    MAX_EXPLAIN_PER_DAY: int = int(os.getenv("MAX_EXPLAIN_PER_DAY", "20"))


settings = Settings()
