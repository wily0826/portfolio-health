# 專案協作說明

本專案有兩份規格書，都在上一層目錄（`AI 投資組合健檢系統/`）：
- `SPEC.md`：主規格（AI 投資組合健檢系統）
- `SPEC-anomaly.md`：擴充模組（財報變動偵測 + AI 解讀）

每次開工：
1. 先讀 `SPEC-anomaly.md` 的 §0 與 §1，再讀 `SPEC.md` 的 §1，確認主線現在在哪一份文件。
2. 做完任何任務，依 `SPEC-anomaly.md` §0 的規則更新：勾選任務（§16）、追加進度日誌（§17）、更新目前狀態（§1）；規格有變動先記決策（§18 的 D-Axx，動到 `SPEC.md` 也要在其 §16 記一筆）。
3. 交付程式碼前必須在本資料夾執行 `python -m pytest`，全部通過才算完成（引擎相關可用 `-W error` 把警告當錯誤）。
4. 規格不明確，或 FinMind 實際回傳與文件描述不符時，先問使用者，不要自己猜。

## 目前進度（2026-10-30）
財報變動偵測模組的「展示切片」已端到端完成並可離線執行：
- 偵測引擎 `app/services/anomaly_engine.py`（純函式）+ `tests/test_anomaly_engine.py`（41 passed）。
- 財報資料源可切換：`FUNDAMENTALS_SOURCE=synthetic`（預設，離線）/ `finmind`（需 token，季報偵測待 SPEC-anomaly A-02）。
- `python -m scripts.seed_demo` 會回補合成財報並跑一次偵測；展示股池刻意對 5 檔製造 5 類旗標。
- 前端：`/dashboard` 持股徽章 + 報告「基本面提醒」；`/radar` 財報變動雷達頁。

下一步：A-02（真實 FinMind 財報驗證、填 `app/services/data_sources/finmind_fundamentals.py` 的 `ITEM_MAP`），之後才是 RAG（A-12~）與評估實驗（A-21~）。
