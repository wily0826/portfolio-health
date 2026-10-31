-- sql/schema.sql — 生產環境 MySQL 8 schema（SPEC §6）
-- MVP 開發 / 展示使用 SQLite（見 app/db.py），本檔為部署 MySQL 時使用。

CREATE TABLE users (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name  VARCHAR(100) NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- symbol 規則：台股用 yfinance 風格，上市 '2330.TW'、上櫃 '6488.TWO'；美股 'AAPL'
CREATE TABLE stocks (
  symbol     VARCHAR(20)  NOT NULL PRIMARY KEY,
  market     ENUM('TW','US') NOT NULL,
  name       VARCHAR(100) NOT NULL,
  sector     VARCHAR(100) NULL,
  currency   CHAR(3)      NOT NULL,          -- 'TWD' / 'USD'
  updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE holdings (
  id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id    INT UNSIGNED NOT NULL,
  symbol     VARCHAR(20)  NOT NULL,
  shares     DECIMAL(18,6) NOT NULL,          -- 股數（支援零股、美股碎股）
  avg_cost   DECIMAL(18,4) NULL,              -- 選填，MVP 不參與計算
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_symbol (user_id, symbol),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (symbol)  REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- close 一律存「還原價」（含股利調整），否則除息日會被誤算成下跌
CREATE TABLE prices (
  symbol     VARCHAR(20) NOT NULL,
  trade_date DATE        NOT NULL,
  close      DECIMAL(18,4) NOT NULL,
  PRIMARY KEY (symbol, trade_date),
  FOREIGN KEY (symbol) REFERENCES stocks(symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- S-02 才需要，MVP 可先不建
CREATE TABLE fx_rates (
  rate_date DATE NOT NULL,
  pair      VARCHAR(10) NOT NULL,             -- 'USDTWD'
  rate      DECIMAL(12,6) NOT NULL,
  PRIMARY KEY (rate_date, pair)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reports (
  id                 INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id            INT UNSIGNED NOT NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  data_as_of         DATE NOT NULL,           -- 使用的最新股價日期
  holdings_snapshot  JSON NOT NULL,           -- 當時的持股 [{symbol, shares}]
  metrics_json       JSON NOT NULL,           -- risk_engine 的 metrics
  risk_score         DECIMAL(5,1) NOT NULL,
  risk_level         VARCHAR(10) NOT NULL,    -- 低 / 中 / 高
  ai_report          TEXT NOT NULL,
  report_source      ENUM('llm','fallback') NOT NULL,
  model_name         VARCHAR(50) NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
