-- sql/schema_anomaly.sql — 財報變動偵測模組 MySQL 8 schema（SPEC-anomaly §8）
-- 展示 / 測試使用 SQLite（見 app/db.py 的 _SCHEMA_SQLITE），本檔為部署 MySQL 時使用。
-- 依賴 sql/schema.sql 的 stocks 表，請先建立核心 schema 再建本檔。
--
-- 本檔包含完整模組的資料表；「展示切片」目前實際使用：
--   universe / fin_month_revenue / fin_statement_items / anomaly_runs / anomalies / anomaly_explanations
-- news / news_fetch_log / eval_labels 為後續 RAG 與評估實驗（A-12~A-23）預留，建表無妨。

CREATE TABLE universe (
  symbol    VARCHAR(20) NOT NULL PRIMARY KEY,
  source    ENUM('list','holding') NOT NULL,
  added_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE fin_month_revenue (
  symbol        VARCHAR(20) NOT NULL,
  revenue_year  SMALLINT    NOT NULL,
  revenue_month TINYINT     NOT NULL,
  revenue       DECIMAL(20,0) NOT NULL,
  fetched_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, revenue_year, revenue_month),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 長表格式；item_type 於 fundamentals_service 回補時已轉為引擎標準欄位名（revenue/gross_profit/...）
CREATE TABLE fin_statement_items (
  symbol      VARCHAR(20)  NOT NULL,
  period_end  DATE         NOT NULL,
  statement   ENUM('IS','BS','CF') NOT NULL,
  item_type   VARCHAR(100) NOT NULL,
  origin_name VARCHAR(200) NULL,
  value       DECIMAL(24,4) NULL,
  fetched_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, period_end, statement, item_type),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE anomaly_runs (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  kind          ENUM('monthly','quarterly') NOT NULL,
  as_of_period  VARCHAR(10) NOT NULL,
  universe_size INT NOT NULL,
  params_json   JSON NOT NULL,                     -- 當次使用的所有門檻（可重現）
  n_flags       INT NULL,
  started_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at   DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE anomalies (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  run_id        INT UNSIGNED NOT NULL,
  symbol        VARCHAR(20) NOT NULL,
  rule_id       VARCHAR(20) NOT NULL,
  period        VARCHAR(10) NOT NULL,
  severity      ENUM('注意','顯著','極端') NOT NULL,
  direction     ENUM('up','down') NOT NULL,
  value         DOUBLE NULL,
  baseline      DOUBLE NULL,
  z             DOUBLE NULL,
  evidence_json JSON NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_flag (symbol, rule_id, period),
  INDEX idx_period_sev (period, severity),
  FOREIGN KEY (run_id) REFERENCES anomaly_runs(id),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE anomaly_explanations (
  anomaly_id      INT UNSIGNED NOT NULL PRIMARY KEY,
  explanation     TEXT NOT NULL,
  cited_news_ids  JSON NOT NULL,                   -- 依 [1]..[n] 的順序存 news.id；備援為 []
  source          ENUM('llm','fallback') NOT NULL,
  model_name      VARCHAR(50) NULL,
  validation_json JSON NULL,                       -- 每次嘗試的驗證結果（含重試）
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ===== 以下為後續 RAG 與評估實驗預留（展示切片尚未使用）=====
CREATE TABLE news (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  symbol          VARCHAR(20)   NOT NULL,
  published_at    DATETIME      NOT NULL,
  title           VARCHAR(500)  NOT NULL,
  description     TEXT          NULL,
  link            VARCHAR(2048) NOT NULL,
  link_hash       CHAR(64)      NOT NULL,
  source          VARCHAR(100)  NULL,
  embedding       JSON          NULL,
  embedding_model VARCHAR(100)  NULL,
  fetched_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_symbol_link (symbol, link_hash),
  INDEX idx_symbol_time (symbol, published_at),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE news_fetch_log (
  symbol     VARCHAR(20) NOT NULL,
  fetch_date DATE        NOT NULL,
  n_items    INT         NOT NULL,
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, fetch_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE eval_labels (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  anomaly_id  INT UNSIGNED NOT NULL,
  eval_type   ENUM('E1','E2') NOT NULL,
  variant     ENUM('rag','no_rag') NULL,
  claim_text  TEXT NULL,
  label       VARCHAR(20) NOT NULL,
  note        TEXT NULL,
  labeled_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
