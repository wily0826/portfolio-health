# report_service.py
# 串接風險引擎 → LLM → guard → reports（SPEC §10、流程強化版 §6）。
# LLM 只拿算好的 metrics JSON，不拿原始股價、不算數字（D-005）。
from __future__ import annotations

import json

from . import guard, llm_client

DISCLAIMER = "本報告僅為依歷史資料計算的風險分析，不構成投資建議，歷史表現不代表未來。"

SYSTEM_PROMPT = """你是投資組合「風險分析」說明員，不是投資顧問。
規則：
1. 只能使用我提供的 JSON 數字，不得自行計算、推測或引用外部數據。
2. 不得建議買進、賣出、加碼、減碼，不得提供目標價或預測股價漲跌。
3. 可以指出「風險特徵」與「值得自行檢視的方向」，例如「產業集中度偏高，可檢視各持股是否來自同一產業」。
4. 用繁體中文、白話、不使用艱深術語；每個專有名詞第一次出現時簡短解釋。
5. 「基本面提醒」段落只能照 fundamental_alerts 的內容客觀陳述（哪一檔、哪個規則、期間、嚴重度、方向），
   不得加入未提供的原因或判斷，不得使用造假、舞弊等指控性用語；fundamental_alerts 為空時寫固定句。
6. 依照指定的 Markdown 結構輸出，不要新增其他段落。"""

_USER_TEMPLATE = """以下是使用者持股的風險指標（JSON，資料截至 {data_as_of}，觀察期約 {n_obs} 個交易日）：
{metrics_json}

請輸出：
## 總評
（2–3 句，包含風險分數與等級）
## 主要風險（最多 3 點）
（每點：發生什麼 → 對應的數字 → 白話意義）
## 配置觀察
（持股與產業分布的特徵）
## 基本面提醒
（依 fundamental_alerts 逐點列出，每點一行；若為空，寫「持股近期沒有偵測到顯著的財報數字變動。」）
## 可自行檢視的方向
（最多 3 點，必須是通用的檢視方向，不得指名買賣特定股票）
## 重要提醒
（固定寫：{disclaimer}）"""


def build_user_prompt(metrics: dict) -> str:
    # 餵給 LLM 的只有 metrics JSON（不含 curve、不含使用者自由輸入文字）→ 防 prompt injection（§10.3）
    return _USER_TEMPLATE.format(
        data_as_of=metrics.get("data_as_of", ""),
        n_obs=metrics.get("n_observations", ""),
        metrics_json=json.dumps(metrics, ensure_ascii=False, indent=2),
        disclaimer=DISCLAIMER,
    )


def generate_report(metrics: dict) -> dict:
    """回傳 {"text", "source", "model_name"}。
    流程：LLM → guard；違規重試 1 次；仍違規或 LLM 失敗 → 規則式備援。"""
    user_prompt = build_user_prompt(metrics)
    try:
        text = llm_client.generate(SYSTEM_PROMPT, user_prompt)
        if guard.is_clean(text):
            return {"text": text, "source": "llm", "model_name": llm_client.model_name()}

        # 第一次違規 → 重試一次，附加禁用詞提示
        violations = guard.find_violations(text)
        retry_prompt = (user_prompt +
                        f"\n\n注意：上一次輸出含有禁止詞彙 {violations}，"
                        f"請勿使用以下詞彙：{guard.BANNED}。")
        text2 = llm_client.generate(SYSTEM_PROMPT, retry_prompt)
        if guard.is_clean(text2):
            return {"text": text2, "source": "llm", "model_name": llm_client.model_name()}
    except llm_client.LLMUnavailable:
        pass  # 走備援

    return {"text": fallback_report(metrics), "source": "fallback", "model_name": None}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


_NONE_ALERTS = "持股近期沒有偵測到顯著的財報數字變動。"
_DIR_LABEL = {"up": "數字向上", "down": "數字向下"}
_SCOPE_LABEL = {"company": "主要是該公司自身的變化",
                "industry": "整個產業都有類似變化"}


def format_alerts(alerts: list[dict] | None) -> str:
    """把 fundamental_alerts 轉成「基本面提醒」的條列（規則式備援與前端共用的敘述口徑）。"""
    if not alerts:
        return f"- {_NONE_ALERTS}"
    lines = []
    for a in alerts:
        name = a.get("name") or a.get("symbol", "")
        parts = [f"{a.get('rule', a.get('rule_id', ''))}", a.get("period", ""),
                 f"嚴重度 {a.get('severity', '')}"]
        extra = _DIR_LABEL.get(a.get("direction"), "")
        scope = _SCOPE_LABEL.get(a.get("scope"))
        tail = "；".join(x for x in (extra, scope) if x)
        line = f"- {name}（{a.get('symbol', '')}）：{'，'.join(p for p in parts if p)}"
        if tail:
            line += f"（{tail}）"
        lines.append(line)
    return "\n".join(lines)


def fallback_report(metrics: dict) -> str:
    """規則式備援報告（SPEC §10.5）：LLM 失敗時仍能產生固定格式報告。"""
    score = metrics["score"]
    weights = metrics.get("weights", {})
    sectors = metrics.get("sector_weights", {})
    top1_sym = metrics.get("top1_symbol", "")
    top_sector = max(sectors, key=sectors.get) if sectors else "未分類"

    # 主要風險（最多 3 點，依子分數排序挑高者）
    sub = score.get("sub_scores", {})
    labels = {
        "top1_weight": f"最大單一持股占比偏高（{top1_sym} 約 {_pct(metrics['top1_weight'])}）",
        "sector_hhi": f"產業集中度偏高（最大產業為「{top_sector}」約 {_pct(sectors.get(top_sector, 0))}）",
        "volatility": f"年化波動度偏高（約 {_pct(metrics['volatility'])}）",
        "max_drawdown_abs": f"歷史最大回撤偏大（約 {_pct(metrics['max_drawdown_abs'])}）",
        "avg_correlation": f"持股間平均相關係數偏高（約 {metrics['avg_correlation']:.2f}）",
    }
    top_risks = sorted(sub.items(), key=lambda kv: kv[1], reverse=True)[:3]
    risk_lines = "\n".join(
        f"- {labels[k]}（風險子分數 {v:.0f}/100）。" for k, v in top_risks if v > 0
    ) or "- 各項風險子分數皆偏低，整體風險特徵相對溫和。"

    single_note = ""
    if metrics.get("is_single_holding"):
        single_note = "\n- 目前僅持有單一標的，沒有分散效果，單一公司事件會直接影響整體。"

    return f"""## 總評

此投資組合的綜合風險分數為 **{score['score']} 分（風險等級：{score['level']}）**。分數為 0–100 的啟發式指標，數值越高代表風險特徵越明顯。{metrics.get('lookback_note', '')}。

## 主要風險

{risk_lines}{single_note}

## 配置觀察

- 共持有 {metrics['n_holdings']} 檔標的，等效持股檔數（考慮權重集中後的有效檔數）約 {metrics['effective_n']:.1f} 檔。
- 最大單一持股為 {top1_sym}，約占 {_pct(metrics['top1_weight'])}。
- 產業分布中最大的是「{top_sector}」，約占 {_pct(sectors.get(top_sector, 0))}。
- 觀察期內年化波動度約 {_pct(metrics['volatility'])}，歷史最大回撤約 {_pct(metrics['max_drawdown_abs'])}，單日 95% 風險值（VaR，過去最差 5% 交易日的單日跌幅）約 {_pct(metrics['var_95_1d'])}。

## 基本面提醒

{format_alerts(metrics.get('fundamental_alerts'))}

## 可自行檢視的方向

- 可檢視各持股是否集中在同一產業或同一題材，評估是否符合自身預期。
- 可檢視整體波動度與最大回撤是否在自己能承受的範圍內。
- 可檢視持股間的相關性，了解在同一波市場變動中是否容易同漲同跌。

## 重要提醒

{DISCLAIMER}
"""
