# auth.py
# 密碼用 bcrypt 雜湊、JWT 放 HttpOnly cookie（SPEC §3、流程強化版 §2 Step2）。
from __future__ import annotations

import datetime as dt

import bcrypt
import jwt
from fastapi import Cookie, Depends

from .config import settings
from .db import get_conn
from .errors import not_authenticated

# bcrypt 單次雜湊上限 72 bytes，超過先截斷（UTF-8 編碼後）。
_BCRYPT_MAX = 72


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def _decode(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def current_user_id(access_token: str | None = Cookie(default=None)) -> int:
    """FastAPI 依賴：從 HttpOnly cookie 取得登入者 user_id；失敗拋 AUTH_REQUIRED。
    所有查詢都以此 user_id 過濾，不信任前端傳來的 user_id（§0.1-7）。"""
    if not access_token:
        raise not_authenticated()
    uid = _decode(access_token)
    if uid is None:
        raise not_authenticated()
    # 確認使用者仍存在
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise not_authenticated()
    return uid


CurrentUser = Depends(current_user_id)
