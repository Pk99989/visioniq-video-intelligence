"""Hybrid retrieval: 0.6 * cosine(embedding) [rescaled to 0..1] +
0.4 * keyword overlap, plus an exact-phrase boost. Reranking is that
combined score, sorted descending. Qdrant is optional: when QDRANT_URL is
set and qdrant-client is installed, vectors are also upserted there;
the SQLite/JSON vectors remain the laptop fallback and the source of
truth for citations (video_id, frame_id, timestamp)."""
import os
import re

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Caption, Detection, Frame, Video
from .embeddings import cosine, embed


def _keyword_score(query: str, text: str) -> float:
    qt = set(re.findall(r"[a-z0-9]+", query.lower()))
    if not qt:
        return 0.0
    tt = set(re.findall(r"[a-z0-9]+", text.lower()))
    return len(qt & tt) / len(qt)


def search_frames(db: Session, query: str, video_id=None, top_k: int = 10, min_score: float = 0.0,
                  user_id=None):
    """Search captions across videos. When user_id is given, only that
    user's own videos are searched — without it, one user could read
    another user's video captions, video ids and frame ids through
    search (the /search endpoint previously passed no owner filter)."""
    qvec, _ = embed(query)
    q = db.query(Caption).join(Frame, Caption.frame_id == Frame.id)
    if user_id is not None:
        q = q.join(Video, Caption.video_id == Video.id).filter(Video.owner_id == user_id)
    if video_id:
        q = q.filter(Caption.video_id == video_id)
    scored = []
    for cap in q.all():
        frame = cap.frame
        emb = frame.embedding() if frame else None
        cos = cosine(qvec, emb) if emb else 0.0
        kw = _keyword_score(query, cap.text)
        score = 0.6 * ((cos + 1.0) / 2.0) + 0.4 * kw
        if query.lower() in cap.text.lower():
            score = min(1.0, score + 0.1)
        if score >= min_score:
            labels = [d.label for d in (frame.detections if frame else [])]
            scored.append({
                "video_id": cap.video_id, "frame_id": cap.frame_id,
                "timestamp_seconds": cap.timestamp_seconds, "score": round(score, 4),
                "caption": cap.text, "frame_path": frame.file_path if frame else None,
                "detections": sorted(set(labels)),
            })
    scored.sort(key=lambda h: h["score"], reverse=True)
    return scored[:top_k]


_qdrant_clients: dict[str, object] = {}


def get_qdrant_client():
    """QDRANT_URL=":memory:" gives an in-memory client (used by tests);
    otherwise a normal HTTP client for QDRANT_URL. Clients are cached
    per URL: an in-memory client holds its state in the instance, so a
    fresh client per call would lose every point just upserted."""
    from qdrant_client import QdrantClient

    url = settings.QDRANT_URL
    if url not in _qdrant_clients:
        if url == ":memory:":
            _qdrant_clients[url] = QdrantClient(":memory:")
        else:
            # qdrant-client builds its httpx client at construction, and
            # httpx chokes on bracketed IPv6 entries in this VM's NO_PROXY
            # list (InvalidURL: Invalid port ':1]') — same workaround as
            # embeddings.py. A plain localhost NO_PROXY is all it needs;
            # restore the originals afterwards.
            old_no_proxy, old_no_proxy_l = os.environ.get("NO_PROXY"), os.environ.get("no_proxy")
            os.environ["NO_PROXY"] = "localhost,127.0.0.1"
            os.environ["no_proxy"] = "localhost,127.0.0.1"
            try:
                _qdrant_clients[url] = QdrantClient(url=url)
            finally:
                if old_no_proxy is None:
                    os.environ.pop("NO_PROXY", None)
                else:
                    os.environ["NO_PROXY"] = old_no_proxy
                if old_no_proxy_l is None:
                    os.environ.pop("no_proxy", None)
                else:
                    os.environ["no_proxy"] = old_no_proxy_l
    return _qdrant_clients[url]


def ensure_qdrant_collection(client=None) -> bool:
    """Create the collection (384-d, cosine) if it does not exist yet.
    Phase 1 upserted points without ever creating the collection, so a
    fresh Qdrant would reject the first upsert."""
    if not settings.QDRANT_URL:
        return False
    try:
        from qdrant_client.models import Distance, VectorParams

        client = client or get_qdrant_client()
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            client.create_collection(
                settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
            )
        return True
    except Exception:
        return False


def try_qdrant_upsert(frame_id: int, vector: list[float], payload: dict) -> bool:
    if not settings.QDRANT_URL:
        return False
    try:
        from qdrant_client.models import PointStruct

        client = get_qdrant_client()
        ensure_qdrant_collection(client)
        client.upsert(settings.QDRANT_COLLECTION,
                      points=[PointStruct(id=frame_id, vector=vector, payload=payload)])
        return True
    except Exception:
        return False


def qdrant_search(vector: list[float], top_k: int = 10, client=None):
    """Vector-only search against Qdrant; returns scored points."""
    from qdrant_client.models import Filter

    client = client or get_qdrant_client()
    ensure_qdrant_collection(client)
    return client.query_points(settings.QDRANT_COLLECTION, query=vector,
                               limit=top_k, with_payload=True).points
