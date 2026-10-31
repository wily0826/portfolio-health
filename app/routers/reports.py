# routers/reports.py — 產生 / 查詢健檢報告（SPEC §11、流程強化版 §7.3）
from __future__ import annotations

import json

import pandas as pd
from fastapi import APIRouter

from ..auth import CurrentUser
from ..config import settings
from ..db import get_conn
from ..errors import insufficient_price_data, no_holdings, report_rate_limit
from ..services import anomaly_service, report_service
from ..services.price_service import (STATUS_READY, get_prices_df, get_sector_map,
                                      symbol_status)
from ..services.risk_engine import InsufficientDataError, analyze

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _today_count(conn, user_id: int) -> int:
    # 可攜寫法：以 Python 算出今日 00:00 當界線，避免用 DB 專屬日期函式
    from datetime import date
    today_start = f"{date.today().isoformat()} 00:00:00"
    return conn.execute(
        "SELECT COUNT(*) AS c FROM reports WHERE user_id = ? AND created_at >= ?",
        (user_id, today_start),
    ).fetchone()["c"]


@router.post("")
def create_report(user_id: int = CurrentUser):
    conn = get_conn()
    try:
        # 每日次數限制（§10.3 控制 LLM 成本）
        if _today_count(conn, user_id) >= settings.MAX_REPORTS_PER_DAY:
            raise report_rate_limit(settings.MAX_REPORTS_PER_DAY)

        rows = conn.execute(
            "SELECT symbol, shares FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise no_holdings()

    symbols = [r["symbol"] for r in rows]
    holdings = pd.DataFrame([{"symbol": r["symbol"], "shares": float(r["shares"])} for r in rows])
    prices = get_prices_df(symbols)
    sector_map = get_sector_map(symbols)

    # 資料不足的股票（供錯誤訊息列出）
    not_ready = [s for s in symbols if symbol_status(s) != STATUS_READY]

    try:
        result = analyze(holdings, prices, sector_map, rf=settings.RISK_FREE_RATE)
    except InsufficientDataError:
        raise insufficient_price_data(not_ready or symbols)
    except ValueError:
        raise insufficient_price_data(not_ready or symbols)

    metrics = result["metrics"]
    curve = result["curve"]

    # 財報變動旗標（SPEC-anomaly §11）：加進給 LLM 的 metrics，產生「基本面提醒」段落。
    # 偵測結果不影響風險分數（D-A03）；取得失敗不應讓健檢失敗，故容錯。
    try:
        alerts = anomaly_service.latest_alerts_for(symbols)
    except Exception:  # noqa: BLE001
        alerts = []
    metrics["fundamental_alerts"] = alerts

    # LLM 只拿 metrics（不含 curve），guard + 備援（§10）
    report = report_service.generate_report(metrics)
    score = metrics["score"]

    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO reports
               (user_id, data_as_of, holdings_snapshot, metrics_json,
                risk_score, risk_level, ai_report, report_source, model_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, metrics["data_as_of"],
             json.dumps([{"symbol": r["symbol"], "shares": float(r["shares"])} for r in rows],
                        ensure_ascii=False),
             json.dumps(metrics, ensure_ascii=False),
             score["score"], score["level"], report["text"],
             report["source"], report["model_name"]),
        )
        conn.commit()
        report_id = cur.lastrowid
    finally:
        conn.close()

    return {
        "report_id": report_id,
        "data_as_of": metrics["data_as_of"],
        "metrics": metrics,
        "curve": {"dates": [p["date"] for p in curve], "values": [p["value"] for p in curve]},
        "ai_report": report["text"],
        "report_source": report["source"],
        "risk_score": score["score"],
        "risk_level": score["level"],
        "fundamental_alerts": metrics.get("fundamental_alerts", []),
    }


@router.get("")
def list_reports(user_id: int = CurrentUser):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, created_at, data_as_of, risk_score, risk_level, report_source
               FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


@router.get("/{report_id}")
def get_report(report_id: int, user_id: int = CurrentUser):
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT * FROM reports WHERE id = ? AND user_id = ?", (report_id, user_id)
        ).fetchone()
    finally:
        conn.close()
    if r is None:
        from ..errors import AppError
        raise AppError("REPORT_NOT_FOUND", "找不到該份報告。", 404)
    metrics = json.loads(r["metrics_json"])
    return {
        "report_id": r["id"],
        "created_at": r["created_at"],
        "data_as_of": r["data_as_of"],
        "metrics": metrics,
        "ai_report": r["ai_report"],
        "report_source": r["report_source"],
        "risk_score": float(r["risk_score"]),
        "risk_level": r["risk_level"],
    }
