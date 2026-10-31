# routers/stocks.py — 以代號或名稱搜尋股票（SPEC §11）
from __future__ import annotations

from fastapi import APIRouter

from ..auth import CurrentUser
from ..db import get_conn

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search(q: str = "", user_id: int = CurrentUser):
    q = q.strip()
    conn = get_conn()
    try:
        if not q:
            rows = conn.execute(
                "SELECT symbol, name, sector, market FROM stocks ORDER BY symbol LIMIT 20"
            ).fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute(
                """SELECT symbol, name, sector, market FROM stocks
                   WHERE symbol LIKE ? OR name LIKE ? ORDER BY symbol LIMIT 20""",
                (like, like),
            ).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}
