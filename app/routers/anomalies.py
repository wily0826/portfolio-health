# routers/anomalies.py — 財報變動雷達 / 旗標詳情 / 持股提醒（SPEC-anomaly §12.1）
# 沿用核心系統的認證與錯誤格式。數字由引擎計算，本層只負責讀寫（D-005）。
from __future__ import annotations

from fastapi import APIRouter, Query

from ..auth import CurrentUser
from ..db import get_conn
from ..errors import AppError
from ..services import anomaly_service, eval_service, explanation_service

router = APIRouter(prefix="/api", tags=["anomalies"])


def _holding_symbols(user_id: int) -> list[str]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT symbol FROM holdings WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()
    return [r["symbol"] for r in rows]


@router.get("/anomalies")
def list_anomalies(
    severity: str | None = Query(default=None),
    rule: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: int = CurrentUser,
):
    return {"items": anomaly_service.list_anomalies(severity, rule, symbol, limit)}


@router.get("/anomalies/{anomaly_id}")
def get_anomaly(anomaly_id: int, user_id: int = CurrentUser):
    detail = anomaly_service.get_anomaly(anomaly_id)
    if detail is None:
        raise AppError("ANOMALY_NOT_FOUND", "找不到該筆財報變動旗標。", 404)
    return detail


@router.post("/anomalies/{anomaly_id}/explain")
def explain_anomaly(anomaly_id: int, force: bool = False, user_id: int = CurrentUser):
    """對單一旗標產生 RAG AI 解讀（抓新聞 → 檢索 → LLM → 引用驗證 → 備援）。"""
    detail = explanation_service.explain(anomaly_id, force=force)
    if detail is None:
        raise AppError("ANOMALY_NOT_FOUND", "找不到該筆財報變動旗標。", 404)
    return detail


@router.get("/holdings/alerts")
def holdings_alerts(user_id: int = CurrentUser):
    """自己持股近期的財報變動旗標（儀表板徽章 / 基本面提醒用）。"""
    symbols = _holding_symbols(user_id)
    return {"items": anomaly_service.latest_alerts_for(symbols)}


@router.post("/anomalies/scan")
def run_scan(user_id: int = CurrentUser):
    """對目前股票清單重跑一次偵測（展示用；synthetic 來源為離線、可重現）。"""
    result = anomaly_service.scan()
    return {"n_flags": result["n_flags"]}


@router.get("/eval/summary")
def eval_summary(user_id: int = CurrentUser):
    """評估實驗彙總（E-1 可解釋比例、E-2 有/無 RAG 的無根據陳述比例）。"""
    return eval_service.summary()


@router.post("/eval/run")
def eval_run(e1_limit: int = 30, e2_limit: int = 20, user_id: int = CurrentUser):
    """重跑評估實驗（會呼叫 LLM；synthetic 來源可離線但無金鑰時走備援，數字較不顯著）。"""
    e2 = eval_service.run_e2(limit=e2_limit)
    e1 = eval_service.run_e1(limit=e1_limit)
    return {"e1": e1, "e2": {"n_flags": e2["n_flags"], "rag": e2["rag"], "no_rag": e2["no_rag"]}}
