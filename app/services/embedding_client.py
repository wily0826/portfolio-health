# embedding_client.py
# 文字向量（SPEC-anomaly §10.1 / A-13）。優先用 Gemini（沿用 T-05 供應商）；
# 無金鑰或失敗時，退回「本地確定性雜湊向量」，讓離線展示與測試仍可排序檢索（品質較粗，簡報須說明）。
from __future__ import annotations

import hashlib

import numpy as np

from ..config import settings

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_LOCAL_DIM = 512


class EmbeddingUnavailable(RuntimeError):
    pass


def embed_texts(texts: list[str]) -> tuple[np.ndarray, str]:
    """回傳 (向量矩陣 shape=[n, dim], 使用的模型名)。Gemini 失敗時自動退回本地向量。"""
    if not texts:
        return np.empty((0, _LOCAL_DIM)), "none"
    if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        try:
            return _gemini_embed(texts), settings.EMBEDDING_MODEL
        except Exception:  # noqa: BLE001 — 退回本地向量，不讓解讀整個失敗
            pass
    return _local_embed(texts), "local-hash"


def _gemini_embed(texts: list[str]) -> np.ndarray:
    import requests

    model = settings.EMBEDDING_MODEL
    url = f"{_GEMINI_BASE}/models/{model}:batchEmbedContents"
    requests_payload = {
        "requests": [
            {"model": f"models/{model}", "content": {"parts": [{"text": t[:2000]}]}}
            for t in texts
        ]
    }
    resp = requests.post(url, headers={"x-goog-api-key": settings.GEMINI_API_KEY},
                         json=requests_payload, timeout=40)
    if resp.status_code != 200:
        raise EmbeddingUnavailable(f"Gemini embed HTTP {resp.status_code}：{resp.text[:160]}")
    embs = resp.json().get("embeddings") or []
    if len(embs) != len(texts):
        raise EmbeddingUnavailable("Gemini embed 回傳筆數不符")
    return np.asarray([e["values"] for e in embs], dtype=float)


def _local_embed(texts: list[str]) -> np.ndarray:
    """中文友善的確定性雜湊向量：以字元 bigram 雜湊進固定維度，再 L2 normalize。"""
    mat = np.zeros((len(texts), _LOCAL_DIM), dtype=float)
    for i, t in enumerate(texts):
        t = t or ""
        grams = [t[j:j + 2] for j in range(max(1, len(t) - 1))] or [t]
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
            mat[i, h % _LOCAL_DIM] += 1.0
        norm = np.linalg.norm(mat[i])
        if norm > 0:
            mat[i] /= norm
    return mat
