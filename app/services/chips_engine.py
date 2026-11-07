# chips_engine.py
# 純函式籌碼面彙總引擎：不碰 DB、不碰網路、不碰 LLM（比照 risk_engine 的設計原則）。
# 把「法人買賣超（股）」與「融資融券餘額（張）」的近 N 日明細，彙總成給前端與 LLM 用的摘要。
# 數字一律由此處確定性計算，LLM 只負責解讀（D-005）。
from __future__ import annotations

SHARES_PER_LOT = 1000  # 台股 1 張 = 1000 股
INVESTORS = ("foreign", "trust", "dealer")  # 外資、投信、自營商
_FLAT_LOTS = 50.0  # 近 N 日法人合計淨買賣超絕對值 < 50 張視為「持平」


def _lots(shares: float) -> float:
    return round(float(shares) / SHARES_PER_LOT, 1)


def _direction(net_lots: float, flat: float = _FLAT_LOTS) -> str:
    if net_lots > flat:
        return "up"      # 近期偏買超（籌碼流入）
    if net_lots < -flat:
        return "down"    # 近期偏賣超（籌碼流出）
    return "flat"


def summarize_chips(
    symbol: str,
    institutional: list[dict],
    margin: list[dict],
    window_days: int = 20,
) -> dict:
    """彙總單一股票的近 window_days 日籌碼明細。

    institutional：每日一筆 {'date','foreign','trust','dealer'}，值為當日「淨買賣超股數」（買-賣，可負）。
    margin：每日一筆 {'date','margin_lots','short_lots'}，值為當日「餘額」（張）。
    回傳可 JSON 序列化的摘要 dict；資料不足時對應欄位為 None。
    """
    inst = sorted(institutional, key=lambda r: r["date"])[-window_days:]
    mgn = sorted(margin, key=lambda r: r["date"])[-window_days:]

    out: dict = {
        "symbol": symbol,
        "window_days": window_days,
        "as_of": None,
        "inst_net_lots": None,
        "foreign_net_lots": None,
        "trust_net_lots": None,
        "dealer_net_lots": None,
        "inst_direction": None,
        "margin_balance_lots": None,
        "margin_change_lots": None,
        "short_balance_lots": None,
        "short_change_lots": None,
        "margin_short_ratio": None,
    }

    if inst:
        sums = {k: sum(float(r.get(k) or 0.0) for r in inst) for k in INVESTORS}
        inst_net_lots = _lots(sum(sums.values()))
        out.update({
            "as_of": inst[-1]["date"],
            "inst_net_lots": inst_net_lots,
            "foreign_net_lots": _lots(sums["foreign"]),
            "trust_net_lots": _lots(sums["trust"]),
            "dealer_net_lots": _lots(sums["dealer"]),
            "inst_direction": _direction(inst_net_lots),
        })

    if mgn:
        first, last = mgn[0], mgn[-1]
        m_now, s_now = float(last["margin_lots"]), float(last["short_lots"])
        out["as_of"] = last["date"] if out["as_of"] is None else max(out["as_of"], last["date"])
        out["margin_balance_lots"] = round(m_now, 1)
        out["margin_change_lots"] = round(m_now - float(first["margin_lots"]), 1)
        out["short_balance_lots"] = round(s_now, 1)
        out["short_change_lots"] = round(s_now - float(first["short_lots"]), 1)
        # 資券比（融資 ÷ 融券）：融券為 0 時不計算，避免除以零
        out["margin_short_ratio"] = round(m_now / s_now, 2) if s_now > 0 else None

    return out
