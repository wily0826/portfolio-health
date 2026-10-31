# llm_client.py
# 封裝 LLM 請求（SPEC §5）。無 API key 或 provider=none 時拋 LLMUnavailable，
# 由 report_service 走規則式備援（D-009 容錯設計）。
from __future__ import annotations

from ..config import settings


class LLMUnavailable(RuntimeError):
    """LLM 無法使用（未設定、逾時、額度用完等）。"""


def model_name() -> str | None:
    if settings.LLM_PROVIDER == "none":
        return None
    if settings.LLM_PROVIDER == "gemini":
        return _gemini_model()
    if settings.LLM_PROVIDER == "openai":
        return settings.LLM_MODEL or "gpt-4o-mini"
    return settings.LLM_MODEL or settings.LLM_PROVIDER


def generate(system_prompt: str, user_prompt: str) -> str:
    """呼叫設定的 LLM，回傳純文字。任何失敗一律轉成 LLMUnavailable。"""
    provider = settings.LLM_PROVIDER
    if provider == "none":
        raise LLMUnavailable("未設定 LLM provider，使用規則式備援報告。")
    try:
        if provider == "openai":
            return _normalize_text(_call_openai(system_prompt, user_prompt))
        if provider == "gemini":
            return _normalize_text(_call_gemini(system_prompt, user_prompt))
        raise LLMUnavailable(f"未知的 LLM provider：{provider}")
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — 統一轉成可備援的錯誤
        raise LLMUnavailable(str(exc)) from exc


def _normalize_text(text: str) -> str:
    r"""修正 LLM 偶發把跳脫序列輸出成字面字元的情況（例如字面的 `\n` 未換行）。
    否則前端 Markdown 逐行渲染與 E-2 的段落解析都會被黏成一行。財報解讀文字
    不含須保留的字面反斜線序列，故此正規化安全。"""
    if not text:
        return text
    return (text.replace("\\r\\n", "\n").replace("\\n", "\n")
                .replace("\\r", "\n").replace("\\t", "\t"))


def _call_openai(system_prompt: str, user_prompt: str) -> str:
    import requests

    if not settings.OPENAI_API_KEY:
        raise LLMUnavailable("缺少 OPENAI_API_KEY。")
    model = settings.LLM_MODEL or "gpt-4o-mini"
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        json={
            "model": model,
            "temperature": settings.LLM_TEMPERATURE,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=40,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# 預設模型；會汰舊，建議在 .env 以 LLM_MODEL 指定，或用 scripts.verify_llm 探索可用模型。
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"


def _gemini_model() -> str:
    return settings.LLM_MODEL or _GEMINI_DEFAULT_MODEL


def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    import requests

    if not settings.GEMINI_API_KEY:
        raise LLMUnavailable("缺少 GEMINI_API_KEY。")
    # 金鑰放 header（x-goog-api-key），不放 URL query，避免出現在 log／網址列
    url = f"{_GEMINI_BASE}/models/{_gemini_model()}:generateContent"
    resp = requests.post(
        url,
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": settings.LLM_TEMPERATURE},
        },
        timeout=40,
    )
    if resp.status_code != 200:
        raise LLMUnavailable(f"Gemini HTTP {resp.status_code}：{resp.text[:200]}")
    body = resp.json()
    candidates = body.get("candidates") or []
    if not candidates:
        # 可能被安全機制擋下或沒有輸出
        raise LLMUnavailable(f"Gemini 無回傳內容：{body.get('promptFeedback', body)}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise LLMUnavailable(f"Gemini 回傳空字串（finishReason={candidates[0].get('finishReason')}）")
    return text


def list_gemini_models() -> list[dict]:
    """列出此金鑰可用、且支援 generateContent 的模型。查詢失敗一律轉 LLMUnavailable。"""
    import requests

    if not settings.GEMINI_API_KEY:
        raise LLMUnavailable("缺少 GEMINI_API_KEY。")
    try:
        resp = requests.get(
            f"{_GEMINI_BASE}/models",
            headers={"x-goog-api-key": settings.GEMINI_API_KEY},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(str(exc)) from exc
    if resp.status_code != 200:
        raise LLMUnavailable(f"ListModels HTTP {resp.status_code}：{resp.text[:200]}")
    out = []
    for m in resp.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            out.append({
                "name": m["name"].split("/")[-1],  # 去掉 'models/' 前綴
                "display_name": m.get("displayName", ""),
            })
    return out
