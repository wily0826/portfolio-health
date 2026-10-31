# routers/auth.py — 註冊 / 登入 / 登出 / 目前使用者（SPEC §11、流程強化版 §7.1）
from __future__ import annotations

from fastapi import APIRouter, Response

from ..auth import CurrentUser, create_token, hash_password, verify_password
from ..config import settings
from ..db import IntegrityError, get_conn
from ..errors import auth_email_exists, auth_invalid
from ..schemas import LoginIn, RegisterIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
        path="/",
    )


@router.post("/register")
def register(body: RegisterIn):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, display_name) VALUES (?, ?, ?)",
            (body.email.lower(), hash_password(body.password), body.display_name),
        )
        conn.commit()
    except IntegrityError:
        raise auth_email_exists()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, response: Response):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (body.email.lower(),)
        ).fetchone()
    finally:
        conn.close()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise auth_invalid()
    _set_cookie(response, create_token(row["id"]))
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, user_id: int = CurrentUser):
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user_id: int = CurrentUser):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}
