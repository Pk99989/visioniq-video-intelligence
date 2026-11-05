"""Embeddings: deterministic hash embedding by default (384-d, L2-normalised),
with real semantic paths when a model is available:

* ``fastembed`` (default real model, Phase 2): BAAI/bge-small-en-v1.5,
  384-d, runs on onnxruntime — no torch, ~130 MB model download on first
  use, CPU-friendly on a 16 GB laptop. Set EMBEDDING_PROVIDER=fastembed.
* ``sentence_transformers``: all-MiniLM-L6-v2, 384-d, needs torch.
  Set EMBEDDING_PROVIDER=sentence_transformers.

Any model failure falls back to the hash embedding; ingestion never
fails on embeddings alone. The provider used is returned so callers
(and tests) can tell a real embedding from the fallback.
"""
import hashlib
import math
import os
import re

from ..config import settings

DIM = settings.EMBEDDING_DIM
_st_model = None
_fastembed_model = None
_fastembed_failed = False


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def hash_embedding(text: str, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
        # second bucket reduces collisions for short captions
        vec[(h >> 16) % dim] += 0.5
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _fastembed(text: str) -> list[float] | None:
    global _fastembed_model, _fastembed_failed
    if _fastembed_failed:
        return None
    try:
        # FastEmbed's model download goes through huggingface_hub/httpx,
        # which chokes on bracketed IPv6 entries in this VM's NO_PROXY
        # list (InvalidURL: Invalid port ':1]'). A plain localhost
        # NO_PROXY is all it needs; restore the originals afterwards.
        # Keep the model cache in the home directory, not /tmp (tmpfs).
        from pathlib import Path

        old_no_proxy, old_no_proxy_l = os.environ.get("NO_PROXY"), os.environ.get("no_proxy")
        os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path.home() / ".cache" / "fastembed"))
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        os.environ["no_proxy"] = "localhost,127.0.0.1"
        try:
            from fastembed import TextEmbedding

            if _fastembed_model is None:
                _fastembed_model = TextEmbedding(model_name=settings.FASTEMBED_MODEL)
        finally:
            if old_no_proxy is None:
                os.environ.pop("NO_PROXY", None)
            else:
                os.environ["NO_PROXY"] = old_no_proxy
            if old_no_proxy_l is None:
                os.environ.pop("no_proxy", None)
            else:
                os.environ["no_proxy"] = old_no_proxy_l
        vec = list(_fastembed_model.embed([text]))[0]
        vec = [float(v) for v in vec]
        if len(vec) != DIM:
            return None
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
    except Exception:
        # Remember the failure: retrying a 3-minute model download on
        # every caption would make ingestion crawl.
        _fastembed_failed = True
        return None


def _sentence_transformers(text: str) -> list[float] | None:
    global _st_model
    try:
        from sentence_transformers import SentenceTransformer

        if _st_model is None:
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = _st_model.encode([text], normalize_embeddings=True)[0].tolist()
        return [float(v) for v in vec]
    except Exception:
        return None


def embed(text: str) -> tuple[list[float], str]:
    provider = os.environ.get("EMBEDDING_PROVIDER", settings.EMBEDDING_PROVIDER)
    if provider == "fastembed":
        vec = _fastembed(text)
        if vec is not None:
            return vec, "fastembed"
    elif provider == "sentence_transformers":
        vec = _sentence_transformers(text)
        if vec is not None:
            return vec, "sentence_transformers"
    return hash_embedding(text), "hash"


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(v * v for v in a)) or 1.0
    nb = math.sqrt(sum(v * v for v in b)) or 1.0
    return dot / (na * nb)
