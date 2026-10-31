# news_service.py
# 新聞讀寫與時間窗（SPEC-anomaly §9 fetch_news_for_flags / §10.1 的 A-12）。
# 只對「有旗標」的公司抓新聞；先查 news_fetch_log 跳過抓過的日期（即使 0 筆也記），避免浪費額度。
from __future__ import annotations

import hashlib
from datetime import timedelta

from ..config import settings
from ..db import IntegrityError, get_conn, upsert_sql
from . import anomaly_engine as eng
from .data_sources.news_base import get_news_source


def _link_hash(link: str) -> str:
    return hashlib.sha256((link or "").encode("utf-8")).hexdigest()


def _window_days(rule_id: str, period: str) -> list:
    start, end = eng.news_window(rule_id, period,
                                 before=settings.NEWS_WINDOW_BEFORE,
                                 after=settings.NEWS_WINDOW_AFTER)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # 控成本：最多抓 NEWS_MAX_DAYS 天，優先抓接近公告日（較新）的日期
    if len(days) > settings.NEWS_MAX_DAYS:
        days = days[-settings.NEWS_MAX_DAYS:]
    return days


def fetch_for_flag(symbol: str, rule_id: str, period: str) -> int:
    """抓取旗標時間窗內的新聞，寫入 news 並記 news_fetch_log。回傳新寫入筆數。"""
    source = get_news_source()
    inserted = 0
    conn = get_conn()
    try:
        for day in _window_days(rule_id, period):
            logged = conn.execute(
                "SELECT 1 FROM news_fetch_log WHERE symbol = ? AND fetch_date = ?",
                (symbol, day.isoformat()),
            ).fetchone()
            if logged:
                continue
            items = source.fetch_day(symbol, day)
            n_ok = 0
            for it in items:
                if not it.get("title") or not it.get("link"):
                    continue
                try:
                    cur = conn.execute(
                        upsert_sql("news",
                                   ["symbol", "published_at", "title", "description",
                                    "link", "link_hash", "source"],
                                   ["symbol", "link_hash"],
                                   ["title", "description", "source"]),
                        (symbol, it["published_at"], it["title"], it.get("description"),
                         it["link"], _link_hash(it["link"]), it.get("source")),
                    )
                    n_ok += 1
                    if cur.rowcount and getattr(cur, "lastrowid", None):
                        inserted += 1
                except IntegrityError:
                    pass
            conn.execute(
                "INSERT INTO news_fetch_log (symbol, fetch_date, n_items) VALUES (?, ?, ?)",
                (symbol, day.isoformat(), n_ok),
            )
            conn.commit()
    finally:
        conn.close()
    return inserted


def get_window_news(symbol: str, rule_id: str, period: str) -> list[dict]:
    """取旗標時間窗內的新聞（標題相同只留一篇），依時間排序。"""
    start, end = eng.news_window(rule_id, period,
                                 before=settings.NEWS_WINDOW_BEFORE,
                                 after=settings.NEWS_WINDOW_AFTER)
    lo = f"{start.isoformat()} 00:00:00"
    hi = f"{(end + timedelta(days=1)).isoformat()} 00:00:00"
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, link, source, published_at, embedding, embedding_model "
            "FROM news WHERE symbol = ? AND published_at >= ? AND published_at < ? "
            "ORDER BY published_at",
            (symbol, lo, hi),
        ).fetchall()
    finally:
        conn.close()
    seen, out = set(), []
    for r in rows:
        if r["title"] in seen:
            continue
        seen.add(r["title"])
        out.append(dict(r))
    return out


def save_embeddings(items: list[dict], vectors, model: str) -> None:
    """把算好的向量寫回 news.embedding（JSON）。items 與 vectors 以列對齊。"""
    import json

    conn = get_conn()
    try:
        for it, vec in zip(items, vectors):
            conn.execute(
                "UPDATE news SET embedding = ?, embedding_model = ? WHERE id = ?",
                (json.dumps([round(float(x), 6) for x in vec]), model, it["id"]),
            )
        conn.commit()
    finally:
        conn.close()
