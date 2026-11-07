# routers/chat.py — 對話式 AI：針對使用者最近一份健檢報告追問（grounding + guard）
from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..db import get_conn
from ..errors import AppError
from ..services import chat_service, prefs_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMsg(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatMsg] = []


def _latest_report_metrics(user_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT metrics_json FROM reports WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row["metrics_json"])
    except (ValueError, TypeError):
        return None


@router.post("")
def chat(body: ChatIn, user_id: int = CurrentUser):
    metrics = _latest_report_metrics(user_id)
    if metrics is None:
        raise AppError("NO_REPORT", "還沒有健檢報告可供問答，請先在首頁產生一次健檢。", 400)
    focus = prefs_service.get_focus(user_id)
    history = [m.model_dump() for m in body.history]
    result = chat_service.answer(body.message, metrics, focus, history)
    return result
