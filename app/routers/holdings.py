# routers/holdings.py — 持股 CRUD + 資料狀態（SPEC §11、流程強化版 §2 Step3/4）
from __future__ import annotations

from fastapi import APIRouter

from ..auth import CurrentUser
from ..db import get_conn, upsert_sql
from ..errors import holding_not_found, invalid_symbol, price_source_error
from ..schemas import HoldingIn, HoldingUpdateIn
from ..services.price_service import symbol_status
from scripts.backfill import backfill_symbol, ensure_stock

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


@router.get("")
def list_holdings(user_id: int = CurrentUser):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT h.id, h.symbol, h.shares, h.avg_cost,
                      s.name, s.sector, s.market,
                      (SELECT close FROM prices p WHERE p.symbol = h.symbol
                       ORDER BY trade_date DESC LIMIT 1) AS last_close
               FROM holdings h JOIN stocks s ON s.symbol = h.symbol
               WHERE h.user_id = ? ORDER BY h.symbol""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    for r in rows:
        last_close = r["last_close"]
        market_value = (float(last_close) * float(r["shares"])) if last_close else None
        items.append({
            "id": r["id"], "symbol": r["symbol"], "name": r["name"],
            "sector": r["sector"], "shares": float(r["shares"]),
            "avg_cost": float(r["avg_cost"]) if r["avg_cost"] is not None else None,
            "last_close": float(last_close) if last_close else None,
            "market_value": market_value,
            "status": symbol_status(r["symbol"]),
        })
    return {"items": items}


@router.post("")
def add_holding(body: HoldingIn, user_id: int = CurrentUser):
    # 1) 確認股票存在於資料來源並建檔；2) 回補歷史價；3) upsert 持股
    try:
        ensure_stock(body.symbol)
    except LookupError:
        raise invalid_symbol(body.symbol)
    except Exception as exc:  # noqa: BLE001
        raise price_source_error(str(exc))

    try:
        backfill_symbol(body.symbol)
    except Exception as exc:  # noqa: BLE001
        raise price_source_error(str(exc))

    conn = get_conn()
    try:
        conn.execute(
            upsert_sql("holdings", ["user_id", "symbol", "shares", "avg_cost"],
                       ["user_id", "symbol"], ["shares", "avg_cost"]),
            (user_id, body.symbol, body.shares, body.avg_cost),
        )
        conn.commit()
        hid = conn.execute(
            "SELECT id FROM holdings WHERE user_id = ? AND symbol = ?",
            (user_id, body.symbol),
        ).fetchone()["id"]
    finally:
        conn.close()
    return {"id": hid, "symbol": body.symbol, "status": symbol_status(body.symbol)}


@router.put("/{holding_id}")
def update_holding(holding_id: int, body: HoldingUpdateIn, user_id: int = CurrentUser):
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE holdings SET shares = ?, avg_cost = ? WHERE id = ? AND user_id = ?",
            (body.shares, body.avg_cost, holding_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise holding_not_found()
    finally:
        conn.close()
    return {"ok": True}


@router.delete("/{holding_id}")
def delete_holding(holding_id: int, user_id: int = CurrentUser):
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding_id, user_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            raise holding_not_found()
    finally:
        conn.close()
    return {"ok": True}
