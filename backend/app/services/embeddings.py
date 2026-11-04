"""Embeddings: deterministic hash embedding by default (384-d, L2-normalised),
with an optional sentence-transformers path when that package + a model are
available. The hash path is honest about what it is: it gives working
keyword-sensitive retrieval on a laptop without a 100MB+ model download,
and it is swapped by setting EMBEDDING_PROVIDER=sentence_transformers.
"""
import hashlib
import math
import re

from ..config import settings

DIM = settings.EMBEDDING_DIM
_st_model = None


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


def embed(text: str) -> tuple[list[float], str]:
    provider = __import__("os").environ.get("EMBEDDING_PROVIDER", "hash")
    if provider == "sentence_transformers":
        global _st_model
        try:
            from sentence_transformers import SentenceTransformer

            if _st_model is None:
                _st_model = SentenceTransformer("all-MiniLM-L6-v2")
            vec = _st_model.encode([text], normalize_embeddings=True)[0].tolist()
            return vec, "sentence_transformers"
        except Exception:
            pass  # fall through to hash embedding; never fail ingestion on this
    return hash_embedding(text), "hash"


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(v * v for v in a)) or 1.0
    nb = math.sqrt(sum(v * v for v in b)) or 1.0
    return dot / (na * nb)
