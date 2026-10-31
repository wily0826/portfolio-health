# eval_service.py
# 評估實驗 E-1 / E-2（SPEC-anomaly §13 / A-21~A-23）。
#
# E-2「引用忠實度」：同一批旗標各產生 RAG 與 無RAG 兩版解讀，把「可能原因」每一點拆出來分類：
#   已標註推測 / 已附來源（[n]）/ 未標示來源。
#   自動指標「無根據陳述比例」= 未標示來源的點數 / 非推測的點數。
#   論點：RAG 強制每點附 [n] 或標推測 → 比例趨近 0；無RAG 不要求 → 會講出一堆沒標來源的斷言。
#   說明：此為「引用紀律」的可重現自動指標（非事實查核）；更細的 支持/部分/不支持 由人工在匯出的
#        CSV 上標註並存回 eval_labels（SPEC §13 建議找同學互標）。
#
# E-1「規則合理性」：取嚴重度最高的 N 個旗標，檢查其 RAG 解讀是否有「附來源」的原因（可解釋）。
#   注意：以合成新聞跑時新聞是刻意植入的，E-1 的「可解釋比例」只有在 NEWS_SOURCE=finmind 下才具意義。
from __future__ import annotations

import json

from ..db import get_conn
from . import anomaly_engine as eng
from . import explanation_service as exs

LABEL_SPEC = "已標註推測"
LABEL_CITED = "已附來源"
LABEL_UNSUPPORTED = "未標示來源"


# ---------- 純函式：拆解與分類 ----------
def extract_causes(text: str) -> list[str]:
    """取「可能原因」段落的條列點（已去掉項目符號）。"""
    section = eng.extract_section(text, "可能原因")
    if not section:
        return []
    return [eng.BULLET_RE.sub("", ln).strip()
            for ln in section.splitlines() if eng.BULLET_RE.match(ln)]


def classify_claim(bullet: str) -> str:
    if any(m in bullet for m in eng.SPECULATION_MARKS):
        return LABEL_SPEC
    if eng.CITE_RE.search(bullet):
        return LABEL_CITED
    return LABEL_UNSUPPORTED


def unsupported_stats(bullets: list[str]) -> dict:
    labels = [classify_claim(b) for b in bullets]
    n = len(labels)
    n_spec = labels.count(LABEL_SPEC)
    n_cited = labels.count(LABEL_CITED)
    n_unsup = labels.count(LABEL_UNSUPPORTED)
    n_nonspec = n - n_spec
    return {
        "n_claims": n, "n_speculation": n_spec, "n_cited": n_cited,
        "n_unsupported": n_unsup, "n_nonspec": n_nonspec,
        "unsupported_ratio": (n_unsup / n_nonspec) if n_nonspec else 0.0,
        "labels": labels,
    }


# ---------- DB 取旗標 ----------
_SEV_RANK = "CASE severity WHEN '極端' THEN 0 WHEN '顯著' THEN 1 ELSE 2 END"


def _pick_flags(limit: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            f"SELECT a.*, s.name, s.sector FROM anomalies a JOIN stocks s ON s.symbol = a.symbol "
            f"ORDER BY {_SEV_RANK}, a.period DESC LIMIT ?", (limit,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "name": r["name"], "sector": r["sector"],
            "flag": {"symbol": r["symbol"], "rule_id": r["rule_id"], "period": r["period"],
                     "value": r["value"], "baseline": r["baseline"], "z": r["z"],
                     "severity": r["severity"], "direction": r["direction"],
                     "evidence": json.loads(r["evidence_json"]) if r["evidence_json"] else {}},
        })
    return out


def _clear_labels(eval_type: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM eval_labels WHERE eval_type = ?", (eval_type,))
        conn.commit()
    finally:
        conn.close()


def _insert_label(conn, anomaly_id, eval_type, variant, claim_text, label, note=None) -> None:
    conn.execute(
        "INSERT INTO eval_labels (anomaly_id, eval_type, variant, claim_text, label, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (anomaly_id, eval_type, variant, claim_text, label, note),
    )


# ---------- E-2 ----------
def run_e2(limit: int = 20, llm_generate=None) -> dict:
    """對前 limit 個旗標各跑 RAG / 無RAG，拆解原因並自動分類、存 eval_labels，回傳彙總。"""
    flags = _pick_flags(limit)
    _clear_labels("E2")
    agg = {"rag": _empty(), "no_rag": _empty()}
    per_flag = []
    conn = get_conn()
    try:
        for item in flags:
            flag, name, sector, aid = item["flag"], item["name"], item["sector"], item["id"]
            rag = exs.generate_rag(flag, name, sector, llm_generate=llm_generate)
            norag = exs.generate_norag(flag, name, sector, llm_generate=llm_generate)
            rec = {"id": aid, "symbol": flag["symbol"], "rule_id": flag["rule_id"]}
            for variant, res in (("rag", rag), ("no_rag", norag)):
                bullets = extract_causes(res.get("text", ""))
                st = unsupported_stats(bullets)
                for b, lab in zip(bullets, st["labels"]):
                    _insert_label(conn, aid, "E2", variant, b, lab, note=res.get("source"))
                _accumulate(agg[variant], st)
                rec[variant] = st
            per_flag.append(rec)
        conn.commit()
    finally:
        conn.close()
    return {"n_flags": len(flags),
            "rag": _finalize(agg["rag"]), "no_rag": _finalize(agg["no_rag"]),
            "per_flag": per_flag}


def _empty() -> dict:
    return {"n_claims": 0, "n_speculation": 0, "n_cited": 0, "n_unsupported": 0, "n_nonspec": 0}


def _accumulate(a: dict, st: dict) -> None:
    for k in ("n_claims", "n_speculation", "n_cited", "n_unsupported", "n_nonspec"):
        a[k] += st[k]


def _finalize(a: dict) -> dict:
    a = dict(a)
    a["unsupported_ratio"] = (a["n_unsupported"] / a["n_nonspec"]) if a["n_nonspec"] else 0.0
    a["cited_ratio"] = (a["n_cited"] / a["n_nonspec"]) if a["n_nonspec"] else 0.0
    return a


# ---------- E-1 ----------
def run_e1(limit: int = 30, llm_generate=None) -> dict:
    """取嚴重度最高的 limit 個旗標，檢查 RAG 解讀是否有附來源的原因（可解釋）。"""
    flags = _pick_flags(limit)
    _clear_labels("E1")
    explainable = 0
    conn = get_conn()
    try:
        for item in flags:
            flag, name, sector, aid = item["flag"], item["name"], item["sector"], item["id"]
            rag = exs.generate_rag(flag, name, sector, llm_generate=llm_generate)
            bullets = extract_causes(rag.get("text", ""))
            has_cited = any(classify_claim(b) == LABEL_CITED for b in bullets)
            label = "可解釋" if has_cited else "找不到"
            explainable += int(has_cited)
            _insert_label(conn, aid, "E1", None, None, label, note=rag.get("source"))
        conn.commit()
    finally:
        conn.close()
    n = len(flags)
    return {"n_flags": n, "n_explainable": explainable,
            "explainable_ratio": (explainable / n) if n else 0.0}


# ---------- 彙總（給 API / eval.html）----------
def summary() -> dict:
    conn = get_conn()
    try:
        e2 = conn.execute(
            "SELECT variant, label, COUNT(*) AS c FROM eval_labels WHERE eval_type='E2' "
            "GROUP BY variant, label").fetchall()
        e1 = conn.execute(
            "SELECT label, COUNT(*) AS c FROM eval_labels WHERE eval_type='E1' "
            "GROUP BY label").fetchall()
    finally:
        conn.close()
    out = {"e2": {"rag": _empty(), "no_rag": _empty()}, "e1": {}}
    for r in e2:
        v = r["variant"]
        if v not in out["e2"]:
            continue
        if r["label"] == LABEL_SPEC:
            out["e2"][v]["n_speculation"] += r["c"]
        elif r["label"] == LABEL_CITED:
            out["e2"][v]["n_cited"] += r["c"]
        elif r["label"] == LABEL_UNSUPPORTED:
            out["e2"][v]["n_unsupported"] += r["c"]
        out["e2"][v]["n_claims"] += r["c"]
    for v in ("rag", "no_rag"):
        a = out["e2"][v]
        a["n_nonspec"] = a["n_claims"] - a["n_speculation"]
        out["e2"][v] = _finalize(a)
    for r in e1:
        out["e1"][r["label"]] = r["c"]
    total_e1 = sum(out["e1"].values())
    out["e1"]["explainable_ratio"] = (out["e1"].get("可解釋", 0) / total_e1) if total_e1 else 0.0
    return out
