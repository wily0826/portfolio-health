# run_anomaly_scan.py — 獨立財報變動掃描（SPEC-anomaly A-20）
# 供排程器（Windows 工作排程器 / Linux cron）定期執行：可選先回補最新財報，
# 再對 stocks 全表（或指定股票）跑一次偵測。資料源由 FUNDAMENTALS_SOURCE 決定，
# 故同一支腳本既可跑 synthetic（離線展示）也可跑 finmind（真實資料，A-11 校準用）。
# 偵測結果以自然鍵 (symbol,rule_id,period) upsert：重跑不漂移 id、保留既有 LLM 解讀（D-A17）。
#
# 用法：
#   python -m scripts.run_anomaly_scan                      # 只掃描現有財報資料
#   python -m scripts.run_anomaly_scan --backfill           # 先回補最新財報再掃描
#   python -m scripts.run_anomaly_scan --symbols 2330.TW,2317.TW
#   python -m scripts.run_anomaly_scan --quiet              # 僅輸出摘要一行（排程日誌用）
#
# 回傳碼：0 成功；1 發生例外（供排程器判斷是否告警）。
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from app.config import settings
from app.db import get_conn, init_db
from app.services import anomaly_service, fundamentals_service


def _universe(symbols_arg: str | None) -> list[str]:
    """掃描範圍：--symbols 指定，或 stocks 全表（ETF／金融保險業由 scan 內部再排除）。"""
    if symbols_arg:
        return [s.strip() for s in symbols_arg.split(",") if s.strip()]
    conn = get_conn()
    try:
        return [r["symbol"] for r in conn.execute("SELECT symbol FROM stocks").fetchall()]
    finally:
        conn.close()


def _backfill(symbols: list[str], quiet: bool) -> None:
    ok = 0
    for sym in symbols:
        try:
            fin = fundamentals_service.backfill_symbol(sym)
            ok += 1
            if not quiet:
                print(f"  {sym}：月營收 {fin['revenue']} 筆 / 報表 {fin['items']} 筆")
        except Exception as exc:  # noqa: BLE001 — 單檔失敗不中斷整批
            print(f"  [WARN] {sym} 回補失敗：{exc}", file=sys.stderr)
    if not quiet:
        print(f"回補完成：{ok}/{len(symbols)} 檔")


def _rule_breakdown(flags: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in flags:
        out[f["rule_id"]] = out.get(f["rule_id"], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="財報變動偵測掃描（可排程）")
    parser.add_argument("--backfill", action="store_true", help="掃描前先回補最新財報")
    parser.add_argument("--symbols", default=None, help="只掃描指定股票（逗號分隔），預設全表")
    parser.add_argument("--quiet", action="store_true", help="僅輸出摘要行")
    args = parser.parse_args(argv)

    started = datetime.now()
    try:
        init_db()
        symbols = _universe(args.symbols)
        if not symbols:
            print("[ERROR] 股票清單為空，請先建立 stocks 或執行 seed/backfill。", file=sys.stderr)
            return 1

        if args.backfill:
            if not args.quiet:
                print(f"回補財報（來源 {settings.FUNDAMENTALS_SOURCE}）…")
            _backfill(symbols, args.quiet)

        if not args.quiet:
            print("跑財報變動偵測…")
        result = anomaly_service.scan(symbols if args.symbols else None)
        flags = result["flags"]
        breakdown = _rule_breakdown(flags)
        elapsed = (datetime.now() - started).total_seconds()

        summary = (f"[{started:%Y-%m-%d %H:%M:%S}] 掃描完成："
                   f"universe={len(symbols)} 旗標={result['n_flags']} "
                   f"耗時={elapsed:.1f}s 來源={settings.FUNDAMENTALS_SOURCE} "
                   f"分布={breakdown or '無'}")
        print(summary)
        return 0
    except Exception as exc:  # noqa: BLE001 — 排程器以回傳碼判斷成敗
        print(f"[ERROR] 掃描失敗：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
