# export_docx.py — T-22：產生專題書 Word 檔（.docx）
# 內容取自 SPEC 與實作/實測結果。body 標楷體、標題微軟正黑體；留校名等 placeholder。
# 用法：python -m scripts.export_docx   → 產出 專題書.docx
from __future__ import annotations

import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

OUT = "專題書.docx"
BODY_FONT = "標楷體"
HEAD_FONT = "微軟正黑體"
MONO_FONT = "Consolas"
NAVY = RGBColor(0x14, 0x23, 0x3B)
GREEN = RGBColor(0x2E, 0x9E, 0x63)
RED = RGBColor(0xD8, 0x50, 0x3A)


def set_eastasia(run, font=BODY_FONT):
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), font)
    rfonts.set(qn("w:ascii"), font)
    rfonts.set(qn("w:hAnsi"), font)


def _style_fonts(doc):
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    for i in (1, 2, 3):
        st = doc.styles[f"Heading {i}"]
        st.font.name = HEAD_FONT
        st.element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
        st.font.color.rgb = NAVY


def h(doc, text, level=1):
    p = doc.add_heading(level=level)
    r = p.add_run(text)
    set_eastasia(r, HEAD_FONT)
    return p


def para(doc, text, size=12, align=None, bold=False, color=None):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    set_eastasia(r, BODY_FONT)
    return p


def code(doc, text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.name = MONO_FONT
    r.font.size = Pt(10.5)
    p.paragraph_format.left_indent = Pt(12)
    return p


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for i, htext in enumerate(headers):
        c = t.rows[0].cells[i]
        c.paragraphs[0].clear()
        r = c.paragraphs[0].add_run(htext)
        r.bold = True
        r.font.size = Pt(11)
        set_eastasia(r, HEAD_FONT)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].paragraphs[0].clear()
            r = cells[i].paragraphs[0].add_run(str(val))
            r.font.size = Pt(10.5)
            set_eastasia(r, BODY_FONT)
    return t


def barviz(doc, label, pct, color):
    """以等寬色塊字元畫水平長條（每 5% 一格），供評估結果對比，無需外部繪圖套件。"""
    p = doc.add_paragraph()
    r1 = p.add_run(f"{label}　")
    r1.font.size = Pt(11)
    set_eastasia(r1, BODY_FONT)
    bar = p.add_run("█" * round(pct / 5) or "▏")
    bar.font.name = MONO_FONT
    bar.font.color.rgb = color
    r3 = p.add_run(f"　{pct:.1f}%")
    r3.bold = True
    r3.font.size = Pt(11)
    r3.font.color.rgb = color
    set_eastasia(r3, BODY_FONT)
    return p


def add_toc(doc):
    # 插入 Word 目錄欄位；於 Word 開啟後按「更新功能變數」即可生成頁碼
    p = doc.add_paragraph()
    run = p.add_run()
    fld = run._element
    from docx.oxml import OxmlElement
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = 'TOC \\o "1-3" \\h \\z \\u'
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate")
    hint = OxmlElement("w:t"); hint.text = "（在 Word 中按 F9 或右鍵「更新功能變數」以產生目錄）"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, sep, hint, end):
        fld.append(el)


def build():
    doc = Document()
    _style_fonts(doc)

    # ---- 封面 ----
    for _ in range(3):
        doc.add_paragraph()
    para(doc, "[＿＿＿＿ 學校名稱 ＿＿＿＿]", 18, WD_ALIGN_PARAGRAPH.CENTER, bold=True)
    para(doc, "[＿＿ 科別 ＿＿] 畢業專題報告", 14, WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(2):
        doc.add_paragraph()
    para(doc, "AI 投資組合健檢系統", 30, WD_ALIGN_PARAGRAPH.CENTER, bold=True, color=NAVY)
    para(doc, "— 以程式計算風險指標、由 LLM 產生白話健檢報告 —", 14,
         WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(3):
        doc.add_paragraph()
    para(doc, "班級：[＿＿＿]　　學號：[＿＿＿]", 14, WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "學生：周東澤", 14, WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "指導老師：[＿＿＿] 老師", 14, WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(2):
        doc.add_paragraph()
    para(doc, "中華民國 115 年 10 月", 14, WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()

    # ---- 摘要 ----
    h(doc, "摘要", 1)
    para(doc,
         "本專題開發一套「AI 投資組合健檢系統」，協助台灣散戶了解自身持股的風險結構。"
         "使用者輸入台股持股後，系統自動取得歷史股價，以 Python（pandas、numpy）計算一組"
         "風險指標，包含權重集中度（HHI）、年化波動度、最大回撤、夏普值與歷史 VaR，"
         "並據此給出 0–100 的綜合風險分數；再由大型語言模型（LLM）將算好的指標"
         "轉成白話的健檢報告，最後以儀表板呈現分數、配置圖與累積報酬曲線。")
    para(doc,
         "系統的核心設計原則是「數字由程式確定性計算，LLM 只負責解讀」：LLM 僅接收已計算完成"
         "的 JSON 指標，不接觸原始股價、也不自行運算，以避免幻覺並確保可重現、可測試。為降低"
         "法規風險，系統定位為「風險分析工具」而非投資顧問，以 prompt 規則與 guard 禁詞雙重"
         "限制避免出現買賣建議，並在 LLM 失效時以規則式備援維持運作。")
    para(doc,
         "系統以 FastAPI 為後端、原生 HTML/JS 搭配 Chart.js 為前端，資料庫採 MySQL 8（開發與"
         "測試可切換 SQLite），股價來源為 FinMind，LLM 採 Gemini。風險引擎通過 34 項單元測試，"
         "並以獨立 numpy 重算（誤差 ≤ 1e-16）與 Excel 公式（≤ 1e-13）交叉驗證，確保計算正確。")
    para(doc,
         "在核心健檢之外，另擴充「財報變動偵測」模組：以穩健統計（中位數 + MAD）自動偵測台股"
         "月營收與季報的顯著變動，再以 RAG（檢索相關新聞 + LLM）產生附來源、可追溯的白話說明，"
         "並以引用驗證確保每點有據、不杜撰。評估實驗顯示，相較直接詢問 LLM，本系統解讀的"
         "「無根據陳述比例」由 100% 降至 0%。全系統目前通過 89 項自動化測試。")
    para(doc, "關鍵詞：投資組合風險、風險指標、HHI、最大回撤、VaR、大型語言模型、"
              "財報變動偵測、RAG、引用驗證、FastAPI、MySQL。",
         12, bold=False)
    doc.add_page_break()

    # ---- 目錄 ----
    h(doc, "目錄", 1)
    add_toc(doc)
    doc.add_page_break()

    # ---- 第一章 ----
    h(doc, "第一章　緒論", 1)
    h(doc, "1.1　研究動機", 2)
    para(doc,
         "多數散戶投資人能從看盤軟體看到帳面損益，卻難以看見持股的「風險結構」：資金是否過度"
         "集中在單一標的或單一產業、整體波動是否超出自身可承受範圍、持股之間是否容易同漲同跌。"
         "這些問題需要統計計算才能量化，對一般投資人門檻偏高。本專題希望以程式自動計算風險指標，"
         "再用 AI 轉成白話，降低理解門檻。")
    h(doc, "1.2　研究目的", 2)
    para(doc, "本系統的 MVP 需使使用者能完成下列流程：")
    para(doc,
         "註冊 → 登入 → 新增台股持股 → 系統驗證代號並取得歷史股價 → 按下「產生健檢」 → "
         "Python 計算風險指標 → LLM 解讀 → 儀表板顯示分數、配置圖、報酬曲線與文字報告。")
    h(doc, "1.3　系統定位", 2)
    para(doc,
         "系統定位為「風險分析工具」，不是投資顧問。不提供個股買賣建議、不給目標價、不預測股價"
         "漲跌。對外提供具體買賣建議可能涉及證券投資顧問相關規範，因此以 prompt 與 guard 雙重"
         "限制把關，並於每份報告附免責聲明。")
    h(doc, "1.4　開發環境與工具", 2)
    table(doc, ["層", "選擇"], [
        ["後端", "Python 3.12 / FastAPI"],
        ["資料處理", "pandas、numpy"],
        ["資料庫", "MySQL 8（生產）／ SQLite（開發·測試），以 DB_BACKEND 切換"],
        ["前端", "原生 HTML + JavaScript + Chart.js"],
        ["股價來源", "FinMind（台股）；synthetic 離線源（展示/測試）"],
        ["LLM", "Gemini（gemini-2.5-flash），透過 llm_client 封裝"],
        ["認證", "bcrypt 密碼雜湊 + JWT（HttpOnly Cookie）"],
        ["排程", "cron（每日更新股價）"],
    ])

    # ---- 第二章 ----
    h(doc, "第二章　系統分析與設計", 1)
    h(doc, "2.1　系統架構", 2)
    para(doc,
         "系統採分層設計。前端只負責畫面、收集表單與呼叫 API；API 層負責驗證請求與身分、呼叫"
         "服務、統一錯誤格式；服務層中的 risk_engine 是純函式，不碰資料庫、網路與 LLM，因此好"
         "測試、答辯好講。資料來源獨立成 adapter，未來商用換授權來源只需改一個檔案。LLM 只拿"
         "算好的 metrics，不拿原始股價。")
    para(doc, "資料流：使用者瀏覽器 → FastAPI（認證/路由）→ risk_engine.analyze() 計算指標 → "
              "report_service 組 prompt 呼叫 LLM → guard 檢查 → 寫入 reports → 回傳儀表板資料。")
    h(doc, "2.2　資料庫設計", 2)
    para(doc, "共五張核心表（另有 S-02 匯率表 fx_rates 預留）。股價一律存「還原價」，避免除息日"
              "被誤判為下跌。reports 表以 JSON 型別保存當時的 metrics 與持股快照。")
    table(doc, ["資料表", "用途", "重點欄位"], [
        ["users", "使用者", "email（唯一）、password_hash、display_name"],
        ["stocks", "股票基本資料", "symbol（PK）、market、name、sector、currency"],
        ["holdings", "持股", "user_id、symbol、shares（支援零股）、avg_cost"],
        ["prices", "歷史還原價", "symbol+trade_date（PK）、close"],
        ["reports", "健檢報告", "metrics_json(JSON)、risk_score、ai_report、report_source"],
    ])
    h(doc, "2.3　資料來源與抓取排程", 2)
    para(doc,
         "資料來源以 PriceSource 介面抽象，實作 FinMind（台股）與 synthetic（離線展示）。"
         "backfill.py 於新增股票時回補過去兩年資料；update_prices.py 由 cron 每交易日 15:00 執行，"
         "只補抓缺漏日期，採 upsert 確保冪等，單一股票失敗不中斷整批並記 log。")
    h(doc, "2.4　API 設計", 2)
    table(doc, ["方法", "路徑", "說明"], [
        ["POST", "/api/auth/register｜login｜logout", "註冊、登入（設 Cookie）、登出"],
        ["GET", "/api/holdings", "列出自己的持股與資料狀態"],
        ["POST/PUT/DELETE", "/api/holdings[/{id}]", "新增/修改/刪除持股"],
        ["POST", "/api/reports", "產生健檢（引擎 → LLM → guard → 存檔）"],
        ["GET", "/api/reports[/{id}]", "歷史報告列表 / 單份報告"],
    ])
    para(doc, "通則：所有查詢以 token 內的 user_id 過濾，不信任前端傳來的 user_id；SQL 一律參數化；"
              "錯誤回應統一為 {\"error\": {\"code\", \"message\", \"details\"}}。")

    # ---- 第三章 ----
    h(doc, "第三章　風險指標與計算引擎", 1)
    h(doc, "3.1　假設與限制", 2)
    para(doc, "採「以目前權重回溯過去一年」計算（固定權重、每日再平衡），非使用者實際歷史績效；"
              "歷史波動不代表未來；只用兩檔以上共同有資料的交易日。")
    h(doc, "3.2　風險指標公式", 2)
    table(doc, ["指標", "意義", "公式（簡）"], [
        ["權重 wᵢ", "各股市值占比", "Vᵢ / ΣVⱼ，Vᵢ = 股數 × 最新還原價"],
        ["年化波動度 σ", "漲跌劇烈程度", "樣本標準差(Rₚ) × √252"],
        ["年化報酬", "幾何年化", "(∏(1+Rₚ,t))^(252/n) − 1"],
        ["夏普值", "每單位風險超額報酬", "(年化報酬 − r_f) / σ，r_f=1.5%"],
        ["最大回撤 MDD", "歷史最慘跌幅", "min(Wₜ / 歷史高 − 1)，≤ 0"],
        ["歷史 VaR 95%", "最差5%交易日單日損失", "−Q₅%(Rₚ)，若為負取 0"],
        ["集中度 HHI / Neff", "持股集中度", "Σwᵢ² ； 有效檔數 = 1/HHI"],
    ])
    h(doc, "3.3　綜合風險分數（0–100，啟發式）", 2)
    para(doc, "各指標先線性映射到 0–100，再加權相加。門檻與權重為自訂啟發式設定，非學術標準，"
              "可在程式的 SCORE_CONFIG 調整。分級：< 30 低、30–60 中、≥ 60 高。")
    table(doc, ["指標", "0 分", "100 分", "權重"], [
        ["最大單一持股 top1_weight", "0.10", "0.50", "30%"],
        ["產業 HHI sector_hhi", "0.15", "0.50", "25%"],
        ["年化波動度 volatility", "0.10", "0.40", "30%"],
        ["最大回撤 |MDD|", "0.05", "0.40", "15%"],
    ])
    h(doc, "3.4　風險引擎實作與邊界處理", 2)
    para(doc, "risk_engine.py 為純函式模組（不碰 DB/網路/LLM）。邊界：共同交易日 < 60 天拋"
              "InsufficientDataError（API 回 422）；價格缺 ≤ 5 天前值填補、> 5 天視為長期停牌拋錯；"
              "產業為空歸「未分類」；分數以 clip 限制在 0–100。")

    # ---- 第四章 ----
    h(doc, "第四章　AI 報告與合規設計", 1)
    h(doc, "4.1　報告流程", 2)
    para(doc, "analyze() 得到 metrics（移除曲線）→ 組 prompt → 呼叫 LLM（temperature 0.3）→ "
              "guard 檢查 → 有違規重試一次 → 仍違規或 LLM 失敗則走規則式備援 → 存入 reports，"
              "以 report_source 記錄 llm 或 fallback。")
    h(doc, "4.2　Prompt 與輸出格式", 2)
    para(doc, "System prompt 要求：只能使用提供的 JSON 數字、不得自行計算或引用外部資料、不得"
              "建議買賣或給目標價、用繁體中文白話說明。固定輸出五段：總評、主要風險、配置觀察、"
              "可自行檢視的方向、重要提醒（免責聲明）。餵給 LLM 的只有 metrics JSON，避免 prompt "
              "injection。")
    h(doc, "4.3　合規 Guard 與備援", 2)
    para(doc, "guard 採保守策略，只要出現禁止詞即視為違規（買進、賣出、加碼、減碼、停損、停利、"
              "目標價、推薦、明牌、保證、必漲、必跌），連「不建議買進」等否定句也會被擋，寧可誤擋"
              "走備援。LLM 失效時以字串模板依 metrics 產生同格式報告，使系統不依賴單一外部服務。")
    h(doc, "4.4　資料隱私與法規", 2)
    para(doc, "持股屬個人財務資訊：全站 HTTPS、密碼 bcrypt 雜湊、提供刪除帳號（ON DELETE CASCADE）、"
              "以匿名 metrics 傳送給 LLM（不含 email 等識別資訊）。商用前應改用授權明確的付費資料源"
              "並諮詢法規。")

    # ---- 第五章 ----
    h(doc, "第五章　系統實作", 1)
    h(doc, "5.1　認證", 2)
    para(doc, "密碼以 bcrypt 雜湊；登入成功簽發 JWT 放入 HttpOnly Cookie，前端不自存 token。"
              "所有需登入的 API 以 Cookie 內的 user_id 過濾資料。")
    h(doc, "5.2　資料庫雙後端與可攜 SQL", 2)
    para(doc, "db.py 以統一的連線包裝支援 SQLite 與 MySQL：呼叫端一律用 ? 佔位符（MySQL 下自動"
              "轉為 %s），並以 upsert_sql() 依後端產生 ON CONFLICT（SQLite）或 ON DUPLICATE KEY "
              "UPDATE（MySQL 8.0.19+）。MySQL 以 docker-compose 提供。")
    h(doc, "5.3　前端儀表板", 2)
    para(doc, "儀表板顯示：風險評分卡（分數＋等級＋五個子分數條）、持股配置圓餅圖、產業配置圖、"
              "累積報酬折線圖、AI 報告與免責聲明，並處理資料不足、缺價、LLM 失敗等錯誤提示。")

    # ---- 第六章 ----
    h(doc, "第六章　測試與驗證", 1)
    h(doc, "6.1　單元測試與引擎驗算", 2)
    para(doc, "風險引擎通過 34 項單元測試，涵蓋 HHI、MDD、VaR、年化報酬等已知答案，並以 wᵀΣw 獨立"
              "計算驗證組合波動度。另以完全獨立的 numpy 程式對三組展示持股重算所有指標，與引擎一致"
              "到 1e-16；再以 Excel 公式（STDEV.S、PERCENTILE.INC、CORREL、SUMPRODUCT）比對到 1e-13。")
    h(doc, "6.2　真實串接與展示案例", 2)
    para(doc, "系統已實際串接 FinMind 台股、Gemini（gemini-2.5-flash）與 MySQL 8 並端到端驗證。"
              "三組展示持股在真實台股資料（資料截至 2026-10-08）下的結果如下：")
    table(doc, ["案例", "風險分數", "最大持股", "年化波動", "最大回撤", "產業HHI"], [
        ["集中型", "78.5（高）", "2330　74.1%", "34.1%", "−16.6%", "1.000"],
        ["分散型", "21.8（低）", "2330　30.0%", "15.4%", "−7.0%", "0.220"],
        ["ETF 型", "78.5（高）", "2330　76.8%", "29.5%", "−12.8%", "0.643"],
    ])
    para(doc, "分數隨集中度與波動上升；展示時不宣稱哪組一定較好，只呈現風險特徵不同。")
    h(doc, "6.3　開發中發現與修正", 2)
    para(doc, "將資料庫擴為雙後端後，以真實 MySQL 測試才發現三項相容性問題並修正：(1) 唯一鍵衝突"
              "例外類別（sqlite3 與 pymysql 不同）；(2) MySQL 的 DECIMAL 欄位回傳為 Decimal，與 float"
              "相乘出錯，於資料邊界統一轉 float；(3) 無參數查詢中的字面 % 被 pymysql 當格式化符號。"
              "此過程顯示跨後端相容性需靠真實環境測試把關。")
    h(doc, "6.4　系統成果展示", 2)
    para(doc, "以「集中型」示範持股（台積電 2000 股、聯發科 300 股、日月光投控 500 股）實際產生的風險健檢"
              "結果如下，數值由程式確定性計算、可重現：")
    table(doc, ["風險分數", "最大單一持股", "產業集中度 HHI", "年化波動度", "最大回撤"], [
        ["78.6（高）", "2330　75.9%", "1.000", "34.0%", "−16.3%"],
    ])
    para(doc, "同一批展示持股的財報變動雷達偵測到五個不同類型的顯著變動旗標，涵蓋全部五項規則：")
    table(doc, ["公司", "規則", "期間", "嚴重度"], [
        ["2330 台積電", "月營收年增率顯著變動", "2026-09", "極端"],
        ["2454 聯發科", "毛利率顯著變動", "2026Q3", "極端"],
        ["2317 鴻海", "應收帳款成長快於營收", "2026Q3", "顯著"],
        ["3008 大立光", "帳面獲利與現金流落差大", "2026Q3", "顯著"],
        ["2308 台達電", "存貨成長快於營收", "2026Q3", "注意"],
    ])
    _shot = os.path.join(os.path.dirname(__file__), "..", "..",
                         "成果展繳交工具", "deliverables", "shots", "radar.png")
    if os.path.exists(_shot):
        doc.add_picture(_shot, width=Inches(6.1))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        para(doc, "圖 6-1　財報變動雷達頁（實際系統畫面）", 10.5, WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
    para(doc, "（儀表板另以甜甜圈圖呈現持股與產業配置、折線圖呈現累積報酬曲線；點開單一旗標可看時間序列與"
              "附新聞來源的 AI 解讀。成果展海報另以簡報化版面呈現上述重點。）")

    # ---- 第七章　擴充模組 ----
    h(doc, "第七章　財報變動偵測與 AI 解讀（擴充模組）", 1)
    h(doc, "7.1　模組動機與定位", 2)
    para(doc, "核心健檢偏重「持股組合」的風險結構；為使系統在答辯時能展現更完整的分析能力，另擴充一個"
              "「財報變動偵測」模組：對台股的月營收與季度財報自動偵測顯著變動，並以 RAG（檢索式生成）"
              "用白話說明可能原因。此模組延續全系統一致的原則——數字一律由程式計算，LLM 僅負責解讀；"
              "且加嚴合規，除了不給買賣建議，也不對公司經營誠信作指控（避免「作假帳」等字眼）。")
    h(doc, "7.2　偵測引擎與五項規則", 2)
    para(doc, "引擎為純函式、可單元測試。以穩健 z 分數（中位數 + MAD，抗極端值）衡量偏離程度，並設"
              "材料性門檻避免小數字放大失真；月營收規則另與同業當月年增率比較，判斷是公司自身或產業"
              "共同現象。五項規則如下：")
    table(doc, ["規則", "偵測內容", "頻率"], [
        ["R-REV-YOY", "月營收年增率顯著偏離自身歷史與同業", "月"],
        ["R-GM-SHIFT", "毛利率較歷史顯著變動", "季"],
        ["R-AR-DIV", "應收帳款成長明顯快於營收", "季"],
        ["R-INV-DIV", "存貨成長明顯快於營收", "季"],
        ["R-ACCRUAL", "帳面獲利與營運現金流落差大（應計項目偏高）", "季"],
    ])
    para(doc, "每個旗標標記嚴重度（注意／顯著／極端）、方向與範圍（公司／產業），並以自然鍵"
              "（股票×規則×期間）寫入資料庫：重跑掃描時更新同一筆、旗標 id 不漂移，且不覆寫使用者"
              "已產生的 AI 解讀。")
    h(doc, "7.3　真實財報串接與驗證", 2)
    para(doc, "季報偵測需正確理解 FinMind 財報欄位語意，否則數字全錯。實測驗證（以 2330、2317、6488 等"
              "為樣本）確認三點並據以實作：(1) 現金流量表為年度累計（YTD），季度值須用相鄰季差分還原；"
              "(2) 損益表為單季值；(3) 資產負債表同時有比率欄位與絕對金額欄位，須取絕對金額。校正後以"
              "真實資料回補 2330，單季營運現金流還原正確，並偵測到真實期別的應收帳款背離旗標。")
    h(doc, "7.4　RAG 解讀流程與合規", 2)
    para(doc, "流程為：抓取該股旗標期間前後的新聞標題 → 以 Gemini 向量模型（含本地雜湊備援）建立語意向量 → "
              "餘弦相似度取出最相關數則 → 交由 LLM 依固定結構生成「發生什麼／可能原因／需要留意」。生成後"
              "程式逐點檢查：每個可能原因必須附新聞編號 [n] 或標註「（推測）」，且不得出現禁止詞彙；違反則"
              "重試一次，再不過則退回規則式備援文字。如此確保 AI 不會「無中生有」。")
    h(doc, "7.5　評估實驗：RAG 的價值", 2)
    para(doc, "為回答「為何不直接問通用聊天機器人」，設計兩項可重現的評估。E-2 對同一批旗標各產生"
              "「有 RAG（本系統，強制引用）」與「沒有 RAG（直接問 LLM）」兩版解讀，統計其「可能原因」中"
              "「既未標示來源、也未標註推測」的斷言比例（即無根據陳述比例，越低越好）。以真實 Gemini"
              "（gemini-2.5-flash）對五個旗標實測：")
    barviz(doc, "有 RAG（本系統）", 0.0, GREEN)
    barviz(doc, "沒有 RAG（直接問）", 100.0, RED)
    table(doc, ["版本", "原因點數", "附來源", "標推測", "未標示來源", "無根據陳述比例"], [
        ["有 RAG（本系統）", "16", "6", "10", "0", "0.0%"],
        ["沒有 RAG（直接問）", "12", "0", "0", "12", "100.0%"],
    ])
    para(doc, "差異來自設計：有 RAG 版在新聞不足以支持某點時，會誠實標「（推測）」而非硬湊來源，因此"
              "非推測的斷言 100% 可回溯到新聞；沒有 RAG 版則產出一整批無來源的斷言。E-1 則檢視嚴重度最高"
              "的旗標中，解讀能附上來源說明的比例，實測為 80%（五個旗標中四個可解釋；此比例在接上真實"
              "新聞來源時最具意義）。此結果量化呈現了 RAG 在「可追溯、不杜撰」上的價值。")

    # ---- 第八章（個人化判讀擴充）----
    h(doc, "第八章　個人化判讀、籌碼面與對話式 AI（擴充模組）", 1)
    h(doc, "8.1　動機：判讀要跟著使用者的需求走", 2)
    para(doc, "健檢報告原本一次把全部指標交給 LLM，產出固定的六段文字。但不同使用者關心的面向不同——"
              "有人只看價格風險，有人想看籌碼面。本章把 AI 判讀改為可由使用者挑選「關注面向」，並新增"
              "「籌碼面」資料維度與一個「對話式 AI」，讓同一份數字能依需求給出不同深度的解讀。"
              "三者皆沿用系統核心原則：數字一律由程式確定性計算，LLM 只負責解讀（D-005）。")
    h(doc, "8.2　關注面向（個人化偏好）", 2)
    para(doc, "提供三個可多選的關注面向，選擇存入 user_prefs 資料表（每位使用者各自記住）；健檢報告與"
              "對話問答都只組裝使用者選到的面向。預設全選，全不選時回全選。")
    table(doc, ["面向", "內容", "資料來源"], [
        ["風險結構", "波動度、最大回撤、集中度等風險指標", "既有風險引擎"],
        ["基本面變動", "財報變動旗標 + RAG 解讀", "財報變動偵測模組（第七章）"],
        ["籌碼面", "三大法人買賣超、融資融券", "新增籌碼模組（8.3）"],
    ])
    para(doc, "同一次改版也移除了對散戶幫助較低、數值常年接近 0 的「平均相關係數」子分數，風險分數改為"
              "四項加權（最大單一持股 30%、產業集中度 25%、年化波動度 30%、最大回撤 15%，和為 1，D-016）。")
    h(doc, "8.3　籌碼面：法人與融資融券", 2)
    para(doc, "籌碼面偵測「誰在買賣、用多少槓桿」。資料來源比照股價與財報，以 CHIPS_SOURCE 切換："
              "synthetic（離線展示，可重現）或 finmind（真實法人買賣超 TaiwanStockInstitutionalInvestorsBuySell、"
              "融資融券 TaiwanStockMarginPurchaseShortSale）。彙總由純函式 chips_engine 完成（不碰 DB/網路/LLM），"
              "與風險引擎同樣可獨立測試。為控成本，籌碼只在使用者選到該面向時即時彙總其持股、不落資料庫。")
    table(doc, ["指標", "意義", "計算（簡）"], [
        ["法人合計買賣超", "外資+投信+自營商近 N 日淨買賣（張）", "Σ(買−賣) ÷ 1000，正為買超"],
        ["融資／融券餘額增減", "近 N 日槓桿部位變化（張）", "期末餘額 − 期初餘額"],
        ["資券比", "融資相對融券的倍數", "融資餘額 ÷ 融券餘額"],
    ])
    para(doc, "儀表板以程式計算的籌碼表呈現方向與張數；為避免與台股「紅漲綠跌」混淆，方向刻意用藍綠（買超）、"
              "紫紅（賣超）、灰（持平），不使用紅綠。")
    h(doc, "8.4　對話式 AI：grounding 而非微調", 2)
    para(doc, "新增 /api/chat 讓使用者針對「自己這份報告」追問。本系統不做模型微調（fine-tune）——對畢業專題"
              "而言成本與資料量都不划算；而是採 grounding：把使用者最近一份報告算好的 metrics（依選的面向裁切）"
              "當成唯一可用事實餵進系統提示，模型只能依這些數字回答，輸出再經既有 guard 擋買賣建議，並以少量"
              "範例問答（few-shot）定調。這正好延續「數字由程式算、LLM 只解讀」的設計，也讓回答可被追溯。")
    para(doc, "合規與邊界：被要求買賣建議或目標價時婉拒並把話題帶回風險說明；問題所需數字不在報告中時據實說明"
              "「這份報告沒有這項資料」，不杜撰；尚未產生健檢報告時回 400 引導先健檢；LLM 不可用時回安全備援訊息。")

    # ---- 第九章 ----
    h(doc, "第九章　結論與未來工作", 1)
    h(doc, "9.1　結論", 2)
    para(doc, "本系統以「數字由程式算、AI 只解讀」為核心，兼顧正確性（可測試、可重現）、合規性"
              "（雙重限制避免買賣建議）與容錯性（規則式備援）。核心 MVP 已完整實作並以真實資料、"
              "真實 LLM 與 MySQL 驗證；並擴充財報變動偵測與 RAG 解讀模組，以評估實驗量化呈現"
              "「有 RAG」相較「直接問 LLM」在來源可追溯性上的明顯優勢。並進一步把判讀個人化（可選關注面向）、"
              "新增籌碼面資料維度，以及以 grounding 方式提供對話式 AI。")
    h(doc, "9.2　已知限制", 2)
    for item in [
        "固定權重回溯，非使用者實際歷史績效。",
        "風險分數門檻為啟發式設定，非學術標準。",
        "ETF 被視為單一產業，產業集中度會失真。",
        "股價取決於第三方，可能延遲或缺漏。",
        "目前使用 FinMind 免費「未還原」股價，除息日會略微高估波動度與最大回撤。",
        "MVP 僅支援台股。",
        "財報變動偵測的嚴重度門檻為啟發式設定，需以更多真實資料逐步校準。",
        "RAG 新聞來源目前僅有標題（FinMind 新聞無摘要欄位），檢索語意較受限。",
        "籌碼面示範預設使用合成資料；接真實 FinMind 前需就法人與融資融券的單位各校準一次。",
        "對話式 AI 依「最近一份報告」grounding，尚未產生報告時無法問答；僅能回答報告內已有的數字。",
    ]:
        para(doc, "・" + item)
    h(doc, "9.3　未來工作", 2)
    para(doc, "歷史健檢比較（S-01）、相關性熱圖（S-05）、美股與匯率（S-02）、ETF 成分股穿透（S-04）、"
              "LINE 通知（S-03），以及升級付費還原價與正式部署；財報變動模組方面，以事件研究驗證旗標"
              "的預測力，並導入公開資訊觀測站重大訊息作為第二新聞來源，以補足新聞僅有標題的限制；"
              "籌碼面可加入法人成本區間與券資比警示，對話式 AI 可加入每日次數上限與對話紀錄保存。")
    h(doc, "9.4　主要設計決策", 2)
    table(doc, ["決策", "內容", "理由"], [
        ["D-005", "數字由程式算，LLM 只解讀", "避免幻覺、可重現、可測試"],
        ["D-007", "定位風險分析工具，guard 禁買賣詞", "降低法規風險"],
        ["D-008", "股價一律存還原價", "避免除息日被誤判下跌"],
        ["D-009", "LLM 失敗用規則式備援", "不依賴單一外部服務"],
        ["D-012", "LLM 定案 Gemini 2.5 Flash", "實測可生成且通過 guard"],
        ["D-013", "開發期用 FinMind 未還原價", "免費方案無還原價權限"],
        ["D-014", "DB 雙後端（SQLite/MySQL）", "測試免裝、答辯可展示 MySQL"],
        ["D-A14", "RAG 新聞改為僅用標題", "FinMind 新聞無摘要欄位，據實調整"],
        ["D-A17", "旗標以自然鍵（股票×規則×期間）upsert", "重掃不改 id、保留既有 AI 解讀"],
        ["D-016", "移除平均相關係數，風險分數改四項加權", "對散戶幫助低、數值常年近 0"],
        ["D-017", "AI 判讀改可選關注面向，存 user_prefs", "判讀跟著使用者需求走"],
        ["D-018", "新增籌碼面，來源 synthetic/finmind 切換", "比照價格/財報的來源 switch 慣例"],
        ["D-019", "對話式 AI 用 grounding + guard，非 fine-tune", "成本/資料量可行，且可追溯"],
    ])

    # ---- 參考 ----
    h(doc, "參考資料", 1)
    for ref in [
        "FinMind 台股開放資料 API 技術文件。",
        "Google Gemini API（Generative Language API）官方文件。",
        "FastAPI、pandas、numpy 官方文件。",
        "投資組合風險與集中度（HHI）、最大回撤、VaR 等財務統計概念。",
    ]:
        para(doc, "・" + ref)

    doc.save(OUT)
    print(f"已產生 {OUT}（九章 + 摘要 + 目錄；body 標楷體、標題微軟正黑體）")
    print("提示：在 Word 開啟後，於目錄處按右鍵「更新功能變數」即可產生頁碼目錄。")


if __name__ == "__main__":
    build()
