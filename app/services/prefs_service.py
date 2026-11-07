# prefs_service.py
# 使用者偏好：AI 判讀的「關注面向」。讓健檢報告與對話式 AI 只聚焦使用者選的面向。
#   risk        風險結構（波動、回撤、集中度）
#   fundamental 基本面變動（財報旗標 + RAG 解讀）
#   chips       籌碼面（法人買賣超、融資融券）
from __future__ import annotations

import json

from ..db import get_conn, upsert_sql

FOCUS_ALL = ["risk", "fundamental", "chips"]
FOCUS_LABELS = {"risk": "風險結構", "fundamental": "基本面變動", "chips": "籌碼面"}


def normalize_focus(focus) -> list[str]:
    """清洗輸入：只留合法面向、去重保序；全空則回全選（預設）。"""
    if not isinstance(focus, (list, tuple)):
        return list(FOCUS_ALL)
    seen, out = set(), []
    for f in focus:
        if f in FOCUS_ALL and f not in seen:
            seen.add(f)
            out.append(f)
    return out or list(FOCUS_ALL)


def get_focus(user_id: int) -> list[str]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT focus_json FROM user_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return list(FOCUS_ALL)
    try:
        return normalize_focus(json.loads(row["focus_json"]))
    except (ValueError, TypeError):
        return list(FOCUS_ALL)


def set_focus(user_id: int, focus) -> list[str]:
    clean = normalize_focus(focus)
    conn = get_conn()
    try:
        conn.execute(
            upsert_sql("user_prefs", ["user_id", "focus_json"], ["user_id"], ["focus_json"]),
            (user_id, json.dumps(clean, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return clean
