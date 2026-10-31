# AI 投資組合健檢系統（MVP 試做版）

使用者輸入台股持股 → 系統用 Python 計算風險指標 → LLM 把結果寫成白話健檢報告 → 儀表板呈現。
本資料夾為依 `SPEC.md` 與「流程強化版規格書」試做的可執行 MVP。

> 定位：**風險分析工具，不是投資顧問**。報告不含買賣建議（guard 雙重限制，見 §13）。

## 與規格的差異（試做取捨）

| 項目 | 規格目標 | 本試做版 | 原因 |
|---|---|---|---|
| 資料庫 | MySQL 8 | **雙後端**：SQLite（測試/開發預設）+ **MySQL 8**（已接，T-02） | `app/db.py` 以 `DB_BACKEND` 切換；MySQL 走 `docker-compose.yml` + `sql/schema.sql` |
| 股價來源 | FinMind 還原價 | **FinMind `TaiwanStockPrice`（未還原）**（已接，D-013）；synthetic 離線源可切換 | 免費 token 無還原價權限（T-03）；未還原為已知限制 |
| LLM | Gemini / OpenAI | **Gemini `gemini-2.5-flash`**（已接，D-012）；無金鑰自動走規則式備援 | T-05 已驗證通過 guard |

> ⚠️ 目前為 FinMind **未還原**股價：除息/除權日會被當成下跌，略微高估波動度與最大回撤（§12.2-6）。
> 商用改付費還原價（`FINMIND_PRICE_DATASET=TaiwanStockPriceAdj`）或自行回推股利。
> 離線展示可改 `PRICE_SOURCE=synthetic`（合成價非真實股價）。

## 快速開始

```bash
cd portfolio-health
python -m pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env

# 建立三組展示持股（集中型 / 分散型 / ETF 型）
python -m scripts.seed_demo

# 啟動
python -m uvicorn app.main:app --reload --port 8000
# 開 http://127.0.0.1:8000
```

### 展示帳號（密碼皆為 `demo1234`）

| 帳號 | 特徵 | 預期 |
|---|---|---|
| `demo-concentrated@example.com` | 幾乎全半導體 | 分數高（集中度、波動高）|
| `demo-diversified@example.com` | 6 檔跨產業 | 分數低（分散效果）|
| `demo-etf@example.com` | 含 0050 / 0056 | 中等；展示 ETF 被視為單一產業的限制 |

實測分數：集中 **62.8（高）** > ETF **48.5（中）** > 分散 **14.2（低）**。

## 測試

```bash
python -m pytest        # 34 passed（風險引擎 22 + guard 4 + API 8）；測試固定用 SQLite
```

## 數字驗算（T-10，答辯佐證）

```bash
python -m scripts.verify_engine        # numpy 第一原理獨立重算，與引擎逐項比對（≤1e-9）
python -m scripts.export_excel ETF型   # 產生 verification.xlsx：用真正的 Excel 公式重算
```

- `verify_engine`：三組展示持股的每個指標都用獨立程式重算一次，證明引擎數字正確、可重現。
- `verification.xlsx`：`prices`→`returns`→`metrics` 三分頁，含 `STDEV.S / PERCENTILE.INC /
  CORREL / SUMPRODUCT` 等 Excel 公式；開啟後 `metrics` 分頁「差異」欄 ≈ 0（已驗證到 ~1e-13）。

## 專題書 / 簡報（T-22）

```bash
python -m scripts.export_docx          # 產生 專題書.docx（七章，body 標楷體）
```

- 簡報為 14 頁 Slides Artifact（含每頁講稿備註與五題答辯問答），可下載 PPTX/PDF。

## 用 MySQL 8（T-02）

```bash
docker compose up -d                 # 啟動 MySQL 8（port 3307，資料存具名 volume）
# .env 設定：
#   DB_BACKEND=mysql
#   MYSQL_HOST=127.0.0.1  MYSQL_PORT=3307  MYSQL_USER=root
#   MYSQL_PASSWORD=devroot  MYSQL_DB=portfolio_health
python -m scripts.seed_demo          # 建表（執行 sql/schema.sql）+ 灌展示資料
python -m uvicorn app.main:app --reload --port 8000
```

- 建表、upsert、每日次數查詢都走可攜寫法；`app/db.py` 的 `upsert_sql()` 會依後端產生
  `ON CONFLICT`（SQLite）或 `ON DUPLICATE KEY UPDATE`（MySQL 8.0.19+）。
- 停止：`docker compose stop`；完全清空（含資料）：`docker compose down -v`。
- 想免 Docker：把 `.env` 的 `DB_BACKEND` 改回 `sqlite` 即可。

## 切換到真實資料 / 真 LLM

在 `.env` 設定：

```ini
PRICE_SOURCE=finmind
FINMIND_TOKEN=你的_token     # ⚠️ 還原價資料集名稱與欄位需先完成 SPEC T-03 核對

LLM_PROVIDER=gemini          # 或 openai
GEMINI_API_KEY=你的_key
```

## 每日股價更新（cron）

```bash
# 台北時間每交易日 15:00
0 15 * * 1-5 cd /path/to/portfolio-health && python -m scripts.update_prices >> logs/update.log 2>&1
```

## 目錄

```
app/
  main.py            FastAPI 入口 + 統一錯誤處理 + 靜態頁
  config.py db.py auth.py schemas.py errors.py
  routers/           auth / stocks / holdings / reports
  services/
    risk_engine.py   §9 純函式風險計算（有單元測試）
    report_service.py LLM → guard → 規則式備援
    llm_client.py guard.py price_service.py
    data_sources/    base（介面）/ finmind / synthetic
scripts/             backfill / update_prices / seed_demo
static/              index.html / dashboard.html（Chart.js）
sql/schema.sql       生產 MySQL schema
tests/               test_risk_engine / test_guard / test_api
```

## 已知限制（簡報主動說明，SPEC §12.2）

1. 固定權重回溯，非使用者實際歷史績效。
2. 風險分數門檻為啟發式設定，非學術標準（可於 `SCORE_CONFIG` 調整）。
3. ETF 被視為單一產業，產業集中度會失真（S-04 可解）。
4. 股價資料取決於第三方，可能延遲或缺漏。
5. MVP 僅台股。
