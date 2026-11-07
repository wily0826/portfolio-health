# db.py
# 雙後端資料層：開發/測試用 SQLite（免安裝），生產用 MySQL 8（schema 見 sql/schema.sql）。
# 呼叫端一律用 `?` 佔位符與 dict 式取欄位（row["x"]）；MySQL 下自動把 `?` 轉成 `%s`。
# SQL 一律參數化（§0.1-7、SPEC §11）。
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import settings

# 跨驅動的「唯一鍵衝突」例外，供呼叫端統一捕捉（sqlite3 / pymysql 類別不同）
_integrity_errors: list[type[Exception]] = [sqlite3.IntegrityError]
try:  # pymysql 未安裝時（純 SQLite 環境）略過
    import pymysql.err as _pymysql_err

    _integrity_errors.append(_pymysql_err.IntegrityError)
except ImportError:
    pass
IntegrityError = tuple(_integrity_errors)

# --- SQLite 建表（對應 sql/schema.sql 的 MySQL 版）---
_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS stocks (
  symbol     TEXT PRIMARY KEY,
  market     TEXT NOT NULL CHECK (market IN ('TW','US')),
  name       TEXT NOT NULL,
  sector     TEXT,
  currency   TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS holdings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  symbol     TEXT NOT NULL,
  shares     REAL NOT NULL,
  avg_cost   REAL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, symbol),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (symbol)  REFERENCES stocks(symbol)
);
CREATE TABLE IF NOT EXISTS prices (
  symbol     TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  close      REAL NOT NULL,
  PRIMARY KEY (symbol, trade_date),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE TABLE IF NOT EXISTS reports (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id           INTEGER NOT NULL,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  data_as_of        TEXT NOT NULL,
  holdings_snapshot TEXT NOT NULL,
  metrics_json      TEXT NOT NULL,
  risk_score        REAL NOT NULL,
  risk_level        TEXT NOT NULL,
  ai_report         TEXT NOT NULL,
  report_source     TEXT NOT NULL CHECK (report_source IN ('llm','fallback')),
  model_name        TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_created ON reports (user_id, created_at);

-- 使用者偏好：AI 判讀的「關注面向」（risk / fundamental / chips），JSON 陣列
CREATE TABLE IF NOT EXISTS user_prefs (
  user_id    INTEGER PRIMARY KEY,
  focus_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ===== 財報變動偵測模組（SPEC-anomaly §8；對應 sql/schema_anomaly.sql 的 MySQL 版）=====
CREATE TABLE IF NOT EXISTS universe (
  symbol   TEXT NOT NULL PRIMARY KEY,
  source   TEXT NOT NULL CHECK (source IN ('list','holding')),
  added_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE TABLE IF NOT EXISTS fin_month_revenue (
  symbol        TEXT    NOT NULL,
  revenue_year  INTEGER NOT NULL,
  revenue_month INTEGER NOT NULL,
  revenue       REAL    NOT NULL,
  fetched_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (symbol, revenue_year, revenue_month),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE TABLE IF NOT EXISTS fin_statement_items (
  symbol      TEXT NOT NULL,
  period_end  TEXT NOT NULL,                       -- 季底日期 YYYY-MM-DD
  statement   TEXT NOT NULL CHECK (statement IN ('IS','BS','CF')),
  item_type   TEXT NOT NULL,                       -- 已轉為引擎標準欄位名（revenue/gross_profit/...）
  origin_name TEXT,
  value       REAL,
  fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (symbol, period_end, statement, item_type),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE TABLE IF NOT EXISTS anomaly_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL CHECK (kind IN ('monthly','quarterly')),
  as_of_period  TEXT NOT NULL,
  universe_size INTEGER NOT NULL,
  params_json   TEXT NOT NULL,                     -- 當次門檻（可重現）
  n_flags       INTEGER,
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT
);
CREATE TABLE IF NOT EXISTS anomalies (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        INTEGER NOT NULL,
  symbol        TEXT NOT NULL,
  rule_id       TEXT NOT NULL,
  period        TEXT NOT NULL,
  severity      TEXT NOT NULL CHECK (severity IN ('注意','顯著','極端')),
  direction     TEXT NOT NULL CHECK (direction IN ('up','down')),
  value         REAL,
  baseline      REAL,
  z             REAL,
  evidence_json TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (symbol, rule_id, period),
  FOREIGN KEY (run_id) REFERENCES anomaly_runs(id),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE INDEX IF NOT EXISTS idx_anom_period_sev ON anomalies (period, severity);
CREATE TABLE IF NOT EXISTS anomaly_explanations (
  anomaly_id      INTEGER NOT NULL PRIMARY KEY,
  explanation     TEXT NOT NULL,
  cited_news_ids  TEXT NOT NULL,                   -- JSON 陣列；備援為 []
  source          TEXT NOT NULL CHECK (source IN ('llm','fallback')),
  model_name      TEXT,
  validation_json TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS news (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol          TEXT NOT NULL,
  published_at    TEXT NOT NULL,
  title           TEXT NOT NULL,
  description     TEXT,
  link            TEXT NOT NULL,
  link_hash       TEXT NOT NULL,                   -- SHA-256(link)
  source          TEXT,
  embedding       TEXT,                            -- JSON float 陣列
  embedding_model TEXT,
  fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (symbol, link_hash),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
);
CREATE INDEX IF NOT EXISTS idx_news_symbol_time ON news (symbol, published_at);
CREATE TABLE IF NOT EXISTS news_fetch_log (
  symbol     TEXT NOT NULL,
  fetch_date TEXT NOT NULL,
  n_items    INTEGER NOT NULL,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (symbol, fetch_date)
);
CREATE TABLE IF NOT EXISTS eval_labels (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  anomaly_id INTEGER NOT NULL,
  eval_type  TEXT NOT NULL CHECK (eval_type IN ('E1','E2')),
  variant    TEXT,                               -- E2：rag / no_rag
  claim_text TEXT,                               -- E2：被標註的那一句原因
  label      TEXT NOT NULL,
  note       TEXT,
  labeled_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE CASCADE
);
"""


class Conn:
    """統一連線包裝：execute/executemany 皆回傳游標，佔位符自動轉換，列為 dict 式。"""

    def __init__(self, raw, backend: str):
        self._raw = raw
        self._backend = backend

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self._backend == "mysql" else sql

    def execute(self, sql: str, params=()):
        if self._backend == "mysql":
            cur = self._raw.cursor()
            # 參數為空時傳 None，避免 pymysql 對 SQL 內字面 % 做格式化（如 LIKE 'x-%'）
            cur.execute(self._sql(sql), params or None)
            return cur
        return self._raw.execute(sql, params)

    def executemany(self, sql: str, seq):
        if self._backend == "mysql":
            cur = self._raw.cursor()
            cur.executemany(self._sql(sql), seq)
            return cur
        return self._raw.executemany(sql, seq)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def _connect_sqlite():
    import sqlite3

    Path(settings.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _connect_mysql():
    import pymysql

    return pymysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DB, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


def get_conn() -> Conn:
    if settings.DB_BACKEND == "mysql":
        return Conn(_connect_mysql(), "mysql")
    return Conn(_connect_sqlite(), "sqlite")


def upsert_sql(table: str, insert_cols: list[str],
               conflict_cols: list[str], update_cols: list[str]) -> str:
    """產生後端對應的 upsert（以 `?` 為佔位符，execute 會自動轉換）。
    MySQL：INSERT ... AS new ON DUPLICATE KEY UPDATE（需 MySQL 8.0.19+）。
    SQLite：INSERT ... ON CONFLICT(...) DO UPDATE SET ... excluded.x。"""
    cols = ", ".join(insert_cols)
    placeholders = ", ".join(["?"] * len(insert_cols))
    if settings.DB_BACKEND == "mysql":
        updates = ", ".join(f"{c}=new.{c}" for c in update_cols)
        return (f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                f"AS new ON DUPLICATE KEY UPDATE {updates}")
    conflict = ", ".join(conflict_cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    return (f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}")


def _mysql_table_exists(conn: Conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        (settings.MYSQL_DB, table_name),
    ).fetchone()
    return bool(row["c"])


def _run_sql_file(conn: Conn, filename: str) -> None:
    schema_path = Path(__file__).resolve().parent.parent / "sql" / filename
    sql_text = schema_path.read_text(encoding="utf-8")
    # 逐一執行（去掉註解行後以分號切分）
    statements = [s.strip() for s in _strip_sql_comments(sql_text).split(";") if s.strip()]
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()


def init_db() -> None:
    conn = get_conn()
    try:
        if settings.DB_BACKEND == "mysql":
            # 核心健檢 schema（以 users 表存在與否判斷是否已建）
            if not _mysql_table_exists(conn, "users"):
                _run_sql_file(conn, "schema.sql")
            # 財報變動偵測 schema（以 anomalies 表存在與否判斷，可獨立補建）
            if not _mysql_table_exists(conn, "anomalies"):
                _run_sql_file(conn, "schema_anomaly.sql")
            # 使用者偏好表（後加的功能）：既有部署已有 users 表，故獨立補建，不走整檔重跑
            if not _mysql_table_exists(conn, "user_prefs"):
                conn.execute(
                    "CREATE TABLE user_prefs ("
                    "  user_id INT UNSIGNED PRIMARY KEY,"
                    "  focus_json JSON NOT NULL,"
                    "  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
                    "    ON UPDATE CURRENT_TIMESTAMP,"
                    "  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
                    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
                )
                conn.commit()
        else:
            conn._raw.executescript(_SCHEMA_SQLITE)  # sqlite 專用
            conn.commit()
    finally:
        conn.close()


def _strip_sql_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)
