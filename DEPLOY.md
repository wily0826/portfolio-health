# Railway 部署指引（AI 投資組合健檢系統）

專案已備妥 Railway 部署所需：`Procfile`（啟動指令，處理動態 `$PORT`）、`requirements.txt`、
`AUTO_SEED`（首次啟動自動建 demo 資料）。config 全用環境變數，密鑰只放 Railway Variables、
不進 git（`.gitignore` 已排除 `.env`／`data/`／`*.db`）。

## 前置
- GitHub 帳號（Railway 從 GitHub 部署最簡單）
- Railway 帳號：railway.app（用 GitHub 登入）

## 步驟 1　把 `portfolio-health` 推上 GitHub
> 只推這個資料夾；`.env`、`data/`、`專題書.docx` 等已被 `.gitignore` 排除，密鑰不會外洩。

在 `portfolio-health/` 目錄執行（可在本工作階段用 `! <指令>` 跑互動式登入）：
```
git init
git add .
git commit -m "portfolio-health: ready for Railway"
# 先在 GitHub 建一個 repo（建議 Private），再把 <你的帳號> 換掉：
git remote add origin https://github.com/<你的帳號>/portfolio-health.git
git branch -M main
git push -u origin main
```

## 步驟 2　Railway 建專案 + MySQL
1. railway.app → **New Project** → **Deploy from GitHub repo** → 選 `portfolio-health`
   （Railway 會偵測 Python + `requirements.txt` + `Procfile` 自動 build）
2. 專案畫面 → **New** → **Database** → **Add MySQL**

## 步驟 3　設環境變數（web service → Variables）
`${{MySQL.XXX}}` 是 Railway 的變數引用語法，把 MySQL plugin 的連線值對應到程式要的名字：
```
DB_BACKEND=mysql
MYSQL_HOST=${{MySQL.MYSQLHOST}}
MYSQL_PORT=${{MySQL.MYSQLPORT}}
MYSQL_USER=${{MySQL.MYSQLUSER}}
MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}
MYSQL_DB=${{MySQL.MYSQLDATABASE}}

JWT_SECRET=<填一段夠長的隨機字串>
COOKIE_SECURE=true

AUTO_SEED=true            # 首次啟動自動建 demo 帳號與資料

# 資料來源（展示建議用 synthetic：離線、快、可重現、不耗額度）
PRICE_SOURCE=synthetic
FUNDAMENTALS_SOURCE=synthetic
NEWS_SOURCE=synthetic

# 要真實 AI 解讀才設；不設則 LLM_PROVIDER 預設 none（走規則式備援，仍可展示）
LLM_PROVIDER=gemini
GEMINI_API_KEY=<你的 Gemini key>

# 只有當 PRICE/FUNDAMENTALS/NEWS 改用 finmind 時才需要（展示用 synthetic 可不填）
# FINMIND_TOKEN=<你的 FinMind token>
```

## 步驟 4　產生網址並驗證
1. web service → **Settings → Networking → Generate Domain**，取得公開網址
2. 第一次啟動時 `AUTO_SEED=true` 會自動建立 demo 資料（synthetic 約數秒）
3. 開網址，用 demo 帳號登入：`demo-concentrated@example.com` / `demo1234`
   （另有 `demo-diversified@…`、`demo-etf@…`，密碼同）

## 注意事項
- **成本**：Railway 有免費試用額度；web + MySQL 持續運行會消耗，成果展期間足夠，長期要留意是否需付費或暫停服務。
- **密鑰安全**：所有 token/key 只放 Railway Variables，永遠不要 commit 進 git（`.env` 已被 gitignore）。
- **資料來源選擇**：展示用 `synthetic`（離線、快、可重現、刻意製造 5 類財報旗標最適合 demo）。若要真實資料，改 `finmind` 並填 `FINMIND_TOKEN`，但首次 seed 會變慢、並消耗 FinMind 免費額度。
- **排程掃描**：`scripts/run_anomaly_scan.py` 可用 Railway 的 Cron（或另開一個 service）定期執行（見 SPEC-anomaly §9.3）。
