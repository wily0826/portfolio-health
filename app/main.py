# main.py — FastAPI 入口（SPEC §5）
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .errors import AppError
from .routers import anomalies, auth, holdings, reports, stocks

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _auto_seed_if_empty() -> None:
    """部署首次啟動：使用者表為空時自動建立 demo 資料（AUTO_SEED=true 時）。失敗不中斷服務。"""
    from .db import get_conn
    try:
        conn = get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        finally:
            conn.close()
        if row and row["c"] == 0:
            from scripts.seed_demo import main as seed_main  # 延遲匯入，避免循環相依
            seed_main()
    except Exception as exc:  # noqa: BLE001 — seed 失敗不應擋住服務啟動
        print(f"[AUTO_SEED] 略過自動 seed：{exc}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.AUTO_SEED:
        _auto_seed_if_empty()
    yield


app = FastAPI(title="AI 投資組合健檢系統", version="0.1.0", lifespan=lifespan)


# --- 統一錯誤格式（流程強化版 §7.2），不外洩 traceback（§0.1-8）---
@app.exception_handler(AppError)
async def _app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content=exc.to_response())


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR",
                           "message": "輸入格式不正確。",
                           "details": {"errors": exc.errors()}}},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(_: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR",
                           "message": "系統發生未預期的錯誤，請稍後再試。",
                           "details": {}}},
    )


app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(holdings.router)
app.include_router(reports.router)
app.include_router(anomalies.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "price_source": settings.PRICE_SOURCE,
            "llm_provider": settings.LLM_PROVIDER, "db_backend": settings.DB_BACKEND}


# --- 前端頁面 ---
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/radar")
def radar():
    return FileResponse(STATIC_DIR / "radar.html")


@app.get("/eval")
def eval_page():
    return FileResponse(STATIC_DIR / "eval.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
