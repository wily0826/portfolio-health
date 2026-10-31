# run_eval.py — 評估實驗 E-1 / E-2（SPEC-anomaly §13 / A-21~A-23）
# 用法：python -m scripts.run_eval [e2_limit] [e1_limit]
#   需先 seed_demo（或對真實資料 scan）產生旗標；LLM 建議用 gemini，否則無RAG 對照會走備援、對比不明顯。
# 產出：終端彙總表 + eval_output/e2_claims.csv（供人工標註 支持/部分支持/不支持，存回 eval_labels）。
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from app.config import settings
from app.db import get_conn, init_db
from app.services import eval_service


def _bar(ratio: float, width: int = 30) -> str:
    n = int(round(ratio * width))
    return "█" * n + "·" * (width - n)


def main(argv: list[str]) -> int:
    e2_limit = int(argv[0]) if argv else 20
    e1_limit = int(argv[1]) if len(argv) > 1 else 30
    init_db()
    print(f"設定：LLM_PROVIDER={settings.LLM_PROVIDER}, NEWS_SOURCE={settings.NEWS_SOURCE}, "
          f"FUNDAMENTALS_SOURCE={settings.FUNDAMENTALS_SOURCE}")
    if settings.LLM_PROVIDER == "none":
        print("⚠️ 未啟用 LLM：兩版解讀都會走規則式備援，E-2 對比不具意義。建議設 LLM_PROVIDER=gemini。")

    print("\n== E-2 引用忠實度（有 RAG vs 無 RAG）==")
    e2 = eval_service.run_e2(limit=e2_limit)
    for v, label in (("rag", "有 RAG（本系統）"), ("no_rag", "無 RAG（直接問）")):
        a = e2[v]
        print(f"\n  {label}：原因點數 {a['n_claims']}（推測 {a['n_speculation']}、"
              f"附來源 {a['n_cited']}、未標示來源 {a['n_unsupported']}）")
        print(f"    無根據陳述比例 = {a['unsupported_ratio']:.1%}  {_bar(a['unsupported_ratio'])}")
    print(f"\n  → 旗標數 {e2['n_flags']}；RAG {e2['rag']['unsupported_ratio']:.1%} vs "
          f"無RAG {e2['no_rag']['unsupported_ratio']:.1%}")

    print("\n== E-1 規則合理性（可解釋比例）==")
    e1 = eval_service.run_e1(limit=e1_limit)
    print(f"  旗標數 {e1['n_flags']}，可解釋 {e1['n_explainable']} → "
          f"可解釋比例 {e1['explainable_ratio']:.1%}  {_bar(e1['explainable_ratio'])}")
    if settings.NEWS_SOURCE != "finmind":
        print("  （註：合成新聞為刻意植入，E-1 比例僅在 NEWS_SOURCE=finmind 下具意義）")

    # 匯出 E-2 原因點，供人工標註 支持/部分支持/不支持（SPEC §13 建議找同學互標）
    out_dir = Path(settings.BASE_DIR) / "eval_output"
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / "e2_claims.csv"
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT anomaly_id, variant, claim_text, label, note FROM eval_labels "
            "WHERE eval_type='E2' ORDER BY anomaly_id, variant").fetchall()
    finally:
        conn.close()
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["anomaly_id", "variant", "claim_text", "auto_label", "source",
                    "human_label(支持/部分支持/不支持/推測)"])
        for r in rows:
            w.writerow([r["anomaly_id"], r["variant"], r["claim_text"], r["label"], r["note"], ""])
    print(f"\n已匯出人工標註檔：{csv_path}（{len(rows)} 列）")

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(eval_service.summary(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"已寫入彙總：{summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
