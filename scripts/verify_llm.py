# verify_llm.py — T-05：LLM API 驗證
# 用假 metrics 跑一次 §10.2 prompt，檢查 guard，並走完整 report_service 流程。
# 用法：先在 .env 設定 LLM_PROVIDER=gemini 與 GEMINI_API_KEY，然後：
#   python -m scripts.verify_llm
from __future__ import annotations

from app.config import settings
from app.services import guard, llm_client, report_service

# 仿 analyze() 輸出的假 metrics（集中型範例，供 LLM 解讀）
FAKE_METRICS = {
    "data_as_of": "2026-10-10",
    "n_holdings": 3,
    "n_observations": 252,
    "lookback_note": "以目前權重回溯計算，非使用者實際歷史績效",
    "is_single_holding": False,
    "weights": {"2330.TW": 0.858, "2454.TW": 0.113, "3711.TW": 0.029},
    "sector_weights": {"半導體業": 1.0},
    "top1_symbol": "2330.TW",
    "top1_weight": 0.858,
    "stock_hhi": 0.749,
    "effective_n": 1.33,
    "sector_hhi": 1.0,
    "volatility": 0.270,
    "annual_return": 0.185,
    "sharpe": 0.63,
    "max_drawdown": -0.134,
    "max_drawdown_abs": 0.134,
    "var_95_1d": 0.027,
    "avg_correlation": 0.01,
    "score": {"score": 62.8, "level": "高",
              "sub_scores": {"top1_weight": 100, "sector_hhi": 100,
                             "volatility": 57, "max_drawdown_abs": 24, "avg_correlation": 0}},
}


def _sep(title: str) -> None:
    print("\n" + "=" * 56 + f"\n{title}\n" + "=" * 56)


def main() -> int:
    _sep("設定")
    print(f"LLM_PROVIDER = {settings.LLM_PROVIDER}")
    print(f"LLM_MODEL    = {settings.LLM_MODEL or '(未指定，用預設)'}")
    has_key = bool(settings.GEMINI_API_KEY or settings.OPENAI_API_KEY)
    print(f"金鑰         = {'已設定' if has_key else '未設定'}")

    if settings.LLM_PROVIDER == "none" or not has_key:
        print("\n⚠️ 尚未設定 LLM。請在 .env 設定 LLM_PROVIDER=gemini 與 GEMINI_API_KEY 後再執行。")
        print("   （未設定時系統會自動走規則式備援報告，仍可正常運作。）")
        return 1

    # 1) 列出此金鑰可用模型（Gemini）
    if settings.LLM_PROVIDER == "gemini":
        _sep("可用模型（支援 generateContent）")
        try:
            models = llm_client.list_gemini_models()
            for m in models:
                mark = "  ←（目前會使用）" if m["name"] == llm_client.model_name() else ""
                print(f"  - {m['name']:<32} {m['display_name']}{mark}")
            names = {m["name"] for m in models}
            if llm_client.model_name() not in names:
                print(f"\n⚠️ 目前設定的模型 {llm_client.model_name()} 不在可用清單中，"
                      f"請於 .env 的 LLM_MODEL 改為上方其中一個。")
                return 1
        except llm_client.LLMUnavailable as exc:
            print(f"列出模型失敗：{exc}")
            return 1

    # 2) 直接呼叫 LLM 跑 §10.2 prompt
    _sep("呼叫 LLM（§10.2 prompt）")
    user_prompt = report_service.build_user_prompt(FAKE_METRICS)
    try:
        raw = llm_client.generate(report_service.SYSTEM_PROMPT, user_prompt)
    except llm_client.LLMUnavailable as exc:
        print(f"❌ 呼叫失敗：{exc}")
        return 1
    print(f"使用模型：{llm_client.model_name()}")
    print(f"回傳長度：{len(raw)} 字\n")
    print(raw)

    # 3) guard 檢查
    _sep("Guard 合規檢查")
    violations = guard.find_violations(raw)
    print("違規詞：" + ("無 ✅" if not violations else f"{violations} ⚠️（會觸發重試／備援）"))

    # 4) 完整 report_service 流程（含重試與備援）
    _sep("完整 generate_report 流程")
    report = report_service.generate_report(FAKE_METRICS)
    print(f"report_source = {report['source']}（llm = LLM 生成；fallback = 規則式備援）")
    print(f"model_name    = {report['model_name']}")
    ok = report["source"] == "llm"
    print("\n" + ("✅ T-05 驗證成功：Gemini 可正常生成且通過 guard。"
                  if ok else "⚠️ 最終走了備援（可能 guard 連續違規或呼叫失敗），請檢視上方輸出。"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
