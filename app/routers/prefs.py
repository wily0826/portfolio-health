# routers/prefs.py — 使用者偏好：AI 判讀的「關注面向」（risk / fundamental / chips）
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import CurrentUser
from ..services import prefs_service

router = APIRouter(prefix="/api/prefs", tags=["prefs"])


class FocusIn(BaseModel):
    focus: list[str]


@router.get("")
def get_prefs(user_id: int = CurrentUser):
    return {"focus": prefs_service.get_focus(user_id), "all": prefs_service.FOCUS_ALL,
            "labels": prefs_service.FOCUS_LABELS}


@router.put("")
def put_prefs(body: FocusIn, user_id: int = CurrentUser):
    return {"focus": prefs_service.set_focus(user_id, body.focus)}
