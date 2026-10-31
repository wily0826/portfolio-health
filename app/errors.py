# errors.py
# 統一錯誤格式（流程強化版 §7.2）：{"error": {"code", "message", "details"}}
# 不把 Python traceback 直接丟給使用者（開發規則 0.1-8）。
from __future__ import annotations


class AppError(Exception):
    """可對外的業務錯誤。status 為 HTTP 狀態碼。"""

    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}

    def to_response(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


# 建議錯誤代碼（流程強化版 §7.2）
def auth_invalid() -> AppError:
    return AppError("AUTH_INVALID_CREDENTIALS", "帳號或密碼錯誤。", 401)


def auth_email_exists() -> AppError:
    return AppError("AUTH_EMAIL_EXISTS", "此 Email 已註冊。", 409)


def not_authenticated() -> AppError:
    return AppError("AUTH_REQUIRED", "請先登入。", 401)


def invalid_symbol(symbol: str) -> AppError:
    return AppError("INVALID_SYMBOL", f"股票代號格式不正確或查無此股票：{symbol}", 422,
                    {"symbol": symbol})


def invalid_shares() -> AppError:
    return AppError("INVALID_SHARES", "股數必須大於 0。", 422)


def holding_not_found() -> AppError:
    return AppError("HOLDING_NOT_FOUND", "找不到該筆持股。", 404)


def no_holdings() -> AppError:
    return AppError("NO_HOLDINGS", "尚未新增任何持股，請先新增持股。", 400)


def insufficient_price_data(symbols: list[str]) -> AppError:
    return AppError("INSUFFICIENT_PRICE_DATA",
                    "部分股票的共同歷史交易日不足（至少需要 60 天）。",
                    422, {"symbols": symbols})


def price_source_error(message: str) -> AppError:
    return AppError("PRICE_SOURCE_ERROR", f"股價資料來源發生錯誤：{message}", 502)


def report_rate_limit(limit: int) -> AppError:
    return AppError("REPORT_RATE_LIMIT", f"今日健檢次數已達上限（{limit} 次），請明日再試。", 429,
                    {"limit": limit})
