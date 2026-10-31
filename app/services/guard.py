# guard.py
# 合規檢查（SPEC §10.4、SPEC-anomaly §7.2）：採保守策略，只要出現禁止詞就視為違規，
# 不分析上下文。寧可誤擋（例如「不建議買進」）也不漏放，誤擋時走重試 / 備援流程。
#
# 兩類禁止詞：
#   ADVICE_WORDS   買賣建議（健檢報告原本就禁用）
#   ACCUSATION_WORDS 指控性用語（財報變動模組新增，避免暗示公司不法，SPEC-anomaly D-A05）
# BANNED 為兩者合集，對外介面（BANNED / find_violations / is_clean）不變，
# report_service 與既有測試不受影響。

ADVICE_WORDS = ["買進", "賣出", "加碼", "減碼", "停損", "停利",
                "目標價", "推薦", "明牌", "保證", "必漲", "必跌"]
ACCUSATION_WORDS = ["造假", "作假", "假帳", "做帳", "舞弊", "掏空", "詐欺", "詐騙", "違法"]
BANNED = ADVICE_WORDS + ACCUSATION_WORDS


def find_violations(text: str) -> list[str]:
    """回傳文字中出現的禁止詞；乾淨文字回傳空 list。"""
    return [w for w in BANNED if w in text]


def is_clean(text: str) -> bool:
    return not find_violations(text)
