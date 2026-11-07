# chat_service.py
# 對話式 AI：讓使用者針對「自己這份健檢報告」追問。沿用現有 Gemini（llm_client）。
#
# 核心原則與健檢報告一致：「數字由程式算、LLM 只解讀」。本層不做真正的模型微調（fine-tune），
# 而是 grounding —— 把使用者「最近一份報告」算好的 metrics（依關注面向裁切）當成唯一可用事實
# 餵給模型，模型只能依這些數字回答；輸出再過 guard 擋買賣建議（D-A23）。
from __future__ import annotations

import json

from . import guard, llm_client
from .prefs_service import FOCUS_LABELS

MAX_HISTORY = 6  # 最多帶入最近幾輪對話，控成本與 prompt injection 面積

SYSTEM_PROMPT = """你是投資組合「風險分析」助理，不是投資顧問。使用者會針對自己的一份健檢報告追問。
規則：
1. 只能根據我提供的「報告數據（JSON）」回答，不得自行計算、推測或引用外部數據或新聞。
2. 不得建議買進、賣出、加碼、減碼，不得提供目標價或預測漲跌；被要求時，禮貌說明本系統只做風險說明，並把話題帶回風險特徵。
3. 若問題所需的數字不在 JSON 中，直說「這份報告沒有這項資料」，不要編造。
4. 用繁體中文、白話、簡短（通常 2–4 句）；需要時可條列。第一次出現的專有名詞簡短解釋。
5. 只回答與這份投資組合風險／財報／籌碼有關的問題；無關問題禮貌婉拒。"""

# few-shot：定調（放進 user prompt，當作風格示範，不是真實資料）
_FEWSHOT = """【回答風格示範】
問：為什麼我的風險分數偏高？
答：主要是集中度——最大單一持股與產業集中度的子分數偏高，代表資金壓在少數標的／同一產業。可自行檢視是否符合你的預期。
問：那我現在該賣掉嗎？
答：這部分無法提供買賣建議。本系統只做風險說明：目前的風險特徵是集中度偏高，是否調整由你自行判斷。"""


def _grounding(metrics: dict, focus: list[str]) -> dict:
    """依關注面向裁切出要餵給模型的事實 JSON（不含股價曲線、不含自由文字）。"""
    score = metrics.get("score", {})
    g: dict = {
        "資料日期": metrics.get("data_as_of"),
        "關注面向": [FOCUS_LABELS.get(f, f) for f in focus],
        "風險分數": score.get("score"),
        "風險等級": score.get("level"),
        "子分數": score.get("sub_scores"),
        "持股檔數": metrics.get("n_holdings"),
        "最大單一持股": metrics.get("top1_symbol"),
        "最大單一持股占比": metrics.get("top1_weight"),
        "產業權重": metrics.get("sector_weights"),
    }
    if "risk" in focus:
        g["風險指標"] = {
            "年化波動度": metrics.get("volatility"),
            "最大回撤": metrics.get("max_drawdown"),
            "單日VaR95": metrics.get("var_95_1d"),
            "等效持股檔數": metrics.get("effective_n"),
            "夏普值": metrics.get("sharpe"),
            "年化報酬": metrics.get("annual_return"),
        }
    if "fundamental" in focus:
        g["財報變動旗標"] = metrics.get("fundamental_alerts", [])
    if "chips" in focus:
        g["籌碼面摘要"] = metrics.get("chip_summary", [])
    return g


def _history_block(history: list[dict] | None) -> str:
    if not history:
        return ""
    rows = []
    for m in history[-MAX_HISTORY:]:
        role = "使用者" if m.get("role") == "user" else "助理"
        content = str(m.get("content", "")).strip()
        if content:
            rows.append(f"{role}：{content}")
    return ("\n【先前對話】\n" + "\n".join(rows)) if rows else ""


def build_prompt(question: str, metrics: dict, focus: list[str], history=None) -> str:
    grounding = json.dumps(_grounding(metrics, focus), ensure_ascii=False, indent=2)
    return (
        f"{_FEWSHOT}\n\n【報告數據（JSON，唯一可用事實）】\n{grounding}\n"
        f"{_history_block(history)}\n\n【使用者問題】\n{question}\n\n"
        f"請依規則，只根據上面的報告數據，用繁體中文簡短回答。"
    )


def answer(question: str, metrics: dict, focus: list[str], history=None) -> dict:
    """回傳 {"text", "source"}。LLM 不可用或違規時回固定備援訊息。"""
    question = (question or "").strip()
    if not question:
        return {"text": "請先輸入問題。", "source": "fallback"}
    prompt = build_prompt(question, metrics, focus, history)
    try:
        text = llm_client.generate(SYSTEM_PROMPT, prompt)
        if guard.is_clean(text):
            return {"text": text, "source": "llm"}
        # 違規（出現買賣建議等禁用詞）→ 不回傳該內容，給安全備援
        return {"text": "這個問題涉及買賣建議，本系統只提供風險與財報、籌碼的客觀說明，無法回答。"
                        "可以換個方式問，例如「哪一項指標讓風險分數偏高？」", "source": "fallback"}
    except llm_client.LLMUnavailable:
        return {"text": "目前 AI 對話功能暫時無法使用（未設定或連線異常）。"
                        "報告中的數字與各面向說明仍可直接參考。", "source": "unavailable"}
