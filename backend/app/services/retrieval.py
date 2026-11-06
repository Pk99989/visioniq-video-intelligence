"""Hybrid retrieval (Phase 4): Qdrant-first vector search with a DB
fallback, metadata filters, query expansion, cross-encoder reranking,
evidence compression, and citation validation.

Read path: Qdrant (when QDRANT_URL is set) returns candidate frame ids
with vector scores -> the DB enriches them (caption text, frame path,
detections — the DB is the source of truth) -> hybrid score (0.6 cosine
+ 0.4 keyword + label bonus + phrase boost) -> optional cross-encoder
rerank -> near-duplicate compression -> top_k. When Qdrant is absent,
errors, or returns no usable points (empty or drifted index), the same
scoring runs over a DB scan of the user's captions.

Embedding granularity decision (audit M9): one caption vector is
stored per *frame* (the same scene vector on every frame of the
scene). That duplicates vectors, but clip retrieval needs
frame-level timestamps, and a per-scene point could not say *when*
in the scene the evidence is. The duplication is the cost; context
compression removes near-identical hits at read time.
"""
import logging
import os
import re

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Caption, Detection, Frame, Video
from .embeddings import cosine, embed

logger = logging.getLogger("visioniq.retrieval")

# Query expansion: generic words map to the detection labels they can
# mean. Expansion only fires for labels actually present in the
# candidate video's detections, so "vehicle" never invents a bus.
_SYNONYMS = {
    "vehicle": {"bus", "car", "truck", "motorcycle", "bicycle", "train"},
    "vehicles": {"bus", "car", "truck", "motorcycle", "bicycle", "train"},
    "person": {"person"},
    "people": {"person"},
    "man": {"person"},
    "woman": {"person"},
    "street": {"bus", "car", "truck"},
    "road": {"bus", "car", "truck"},
    "traffic": {"bus", "car", "truck"},
    "dog": {"dog"},
    "cat": {"cat"},
    "football": {"sports ball"},
    "soccer": {"sports ball"},
    "bike": {"bicycle", "motorcycle"},
}


def expand_query_terms(query: str, labels_present: set[str]) -> set[str]:
    """Query words plus synonym labels that are actually detected in
    the video. Used for keyword scoring and the label bonus.
    Stopwords are dropped first so expansion works on content words."""
    terms = _content_terms(query)
    for word in list(terms):
        for label in _SYNONYMS.get(word, set()):
            if label in labels_present:
                terms.add(label)
    return terms


def _keyword_score(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    tt = set(re.findall(r"[a-z0-9]+", text.lower()))
    return len(query_terms & tt) / len(query_terms)


# Stopwords are removed from query terms before keyword scoring and
# expansion: without this, "is there a truck in the video?" matches
# any caption containing "in" or "the" and a negative question looks
# like evidence. Content words are what must match.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "in", "on",
    "at", "to", "of", "for", "with", "by", "and", "or", "there", "here",
    "what", "which", "who", "whom", "whose", "it", "its", "this", "that",
    "these", "those", "do", "does", "did", "how", "many", "much", "show",
    "me", "please", "i", "you", "he", "she", "we", "they", "my", "your",
    "his", "her", "our", "their", "as", "from", "into", "over", "under",
    "between", "about", "after", "before", "during", "isnt", "arent",
}


def _content_terms(query: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in _STOPWORDS}


def _hybrid_score(cos: float, kw: float, label_hit: bool, phrase: bool) -> float:
    score = 0.6 * ((cos + 1.0) / 2.0) + 0.4 * kw
    if label_hit:
        score = min(1.0, score + 0.05)
    if phrase:
        score = min(1.0, score + 0.1)
    return round(score, 4)


def compress_hits(hits: list[dict], window_seconds: float = 2.0) -> list[dict]:
    """Context compression: drop near-identical evidence — same video,
    same caption text, timestamps within the window. Keeps the
    highest-scored copy. A search answer should not cite the same
    moment five times."""
    kept = []
    for h in hits:
        duplicate = any(
            k["video_id"] == h["video_id"] and k["caption"] == h["caption"]
            and abs(k["timestamp_seconds"] - h["timestamp_seconds"]) <= window_seconds
            for k in kept)
        if not duplicate:
            kept.append(h)
    return kept


def validate_citations(db: Session, citations: list[dict]) -> list[dict]:
    """Every citation must resolve to a real stored frame (same video,
    same frame id, timestamp within 1 s of the stored frame). Drops
    anything that does not — an answer must never cite a frame that
    does not exist."""
    valid = []
    for c in citations:
        frame_id = c.get("frame_id")
        if frame_id is None:
            continue
        frame = db.get(Frame, frame_id)
        if frame is None or frame.video_id != c.get("video_id"):
            continue
        if abs(frame.timestamp_seconds - c.get("timestamp_seconds", 0)) > 1.0:
            continue
        valid.append(c)
    return valid


# ---------------------------------------------------------------- Qdrant

_qdrant_clients: dict[str, object] = {}
_reranker = None
_reranker_failed = False


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
    except Exception as exc:
        logger.warning("qdrant ensure_collection failed: %s", exc)
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
    except Exception as exc:
        # No longer swallowed silently (audit H3): a failing vector
        # store means search silently degrades to the DB scan.
        logger.warning("qdrant upsert failed frame_id=%s: %s", frame_id, exc)
        return False


def _qdrant_filter(user_id=None, video_id=None, label=None, provider=None,
                   start_seconds=None, end_seconds=None):
    """Payload filter for the read path. owner_id is the privacy
    boundary: without it, Qdrant would return other users' points."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

    must = []
    if user_id is not None:
        must.append(FieldCondition(key="owner_id", match=MatchValue(value=user_id)))
    if video_id:
        must.append(FieldCondition(key="video_id", match=MatchValue(value=video_id)))
    if label:
        must.append(FieldCondition(key="detections", match=MatchValue(value=label)))
    if provider:
        must.append(FieldCondition(key="provider", match=MatchValue(value=provider)))
    if start_seconds is not None or end_seconds is not None:
        must.append(FieldCondition(key="timestamp_seconds",
                                   range=Range(gte=start_seconds, lte=end_seconds)))
    return Filter(must=must) if must else None


def qdrant_search(vector: list[float], top_k: int = 10, client=None, **filters):
    """Vector search against Qdrant with payload filters; returns
    scored points. Kept as the low-level helper; search_frames is the
    read path that enriches and scores them."""
    client = client or get_qdrant_client()
    ensure_qdrant_collection(client)
    return client.query_points(
        settings.QDRANT_COLLECTION, query=vector, limit=top_k,
        query_filter=_qdrant_filter(**filters), with_payload=True).points


def reindex_qdrant(db: Session) -> dict:
    """Rebuild the Qdrant collection from the DB (all users' frames,
    with owner payloads). Used by scripts/reindex_qdrant.py after a
    code change to the payload shape, or to repair drift. Returns
    counts; raises on Qdrant errors so a bad rebuild is visible."""
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = get_qdrant_client()
    if client.collection_exists(settings.QDRANT_COLLECTION):
        client.delete_collection(settings.QDRANT_COLLECTION)
    client.create_collection(
        settings.QDRANT_COLLECTION,
        vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE))
    frames = db.query(Frame).filter(Frame.embedding_json.isnot(None)).all()
    points, skipped = [], 0
    for frame in frames:
        cap = (db.query(Caption).filter_by(frame_id=frame.id)
               .order_by(Caption.id).first())
        video = db.get(Video, frame.video_id)
        if not video:
            skipped += 1
            continue
        import json

        labels = sorted({d.label for d in frame.detections})
        points.append(PointStruct(
            id=frame.id, vector=json.loads(frame.embedding_json),
            payload={"video_id": frame.video_id, "owner_id": video.owner_id,
                     "timestamp_seconds": frame.timestamp_seconds,
                     "caption": cap.text if cap else "",
                     "provider": cap.provider if cap else "fallback",
                     "detections": labels}))
    for i in range(0, len(points), 100):
        client.upsert(settings.QDRANT_COLLECTION, points=points[i:i + 100])
    return {"upserted": len(points), "skipped": skipped}


# ---------------------------------------------------------------- reranking

def _get_reranker():
    """Lazy cross-encoder (fastembed TextCrossEncoder). Downloads the
    model on first use (~80 MB for MiniLM-L-6-v2); returns None when
    disabled (RERANKER_MODEL empty) or when the model cannot load —
    search then keeps the hybrid order instead of failing."""
    global _reranker, _reranker_failed
    if _reranker is not None:
        return _reranker
    if _reranker_failed or not settings.RERANKER_MODEL:
        return None
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        # Same NO_PROXY workaround as get_qdrant_client: httpx (used
        # by the Hugging Face download) chokes on bracketed IPv6
        # entries in this VM's NO_PROXY list.
        old_no_proxy, old_no_proxy_l = os.environ.get("NO_PROXY"), os.environ.get("no_proxy")
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        os.environ["no_proxy"] = "localhost,127.0.0.1"
        try:
            # Local cache first: the hub API calls in the online path
            # have no timeout and a flaky proxy can stall a search
            # for minutes. Only when the model is not cached at all
            # do we attempt the download.
            try:
                _reranker = TextCrossEncoder(model_name=settings.RERANKER_MODEL,
                                             local_files_only=True)
            except Exception:
                _reranker = TextCrossEncoder(model_name=settings.RERANKER_MODEL)
        finally:
            if old_no_proxy is None:
                os.environ.pop("NO_PROXY", None)
            else:
                os.environ["NO_PROXY"] = old_no_proxy
            if old_no_proxy_l is None:
                os.environ.pop("no_proxy", None)
            else:
                os.environ["no_proxy"] = old_no_proxy_l
        logger.info("reranker loaded model=%s", settings.RERANKER_MODEL)
        return _reranker
    except Exception as exc:
        _reranker_failed = True
        logger.warning("reranker failed to load model=%s: %s", settings.RERANKER_MODEL, exc)
        return None


def rerank_hits(query: str, hits: list[dict]) -> list[dict]:
    """Cross-encoder rerank of already-scored hits. Final score is
    0.5 * hybrid + 0.5 * min-max normalised reranker score, so the
    reranker reorders but cannot invent evidence. Returns hits sorted
    by the blended score, or the input unchanged when disabled."""
    reranker = _get_reranker()
    if reranker is None or not hits:
        return hits
    try:
        scores = list(reranker.rerank(query, [h["caption"] for h in hits]))
    except Exception as exc:
        logger.warning("reranker failed at query time: %s", exc)
        return hits
    lo, hi = min(scores), max(scores)
    for h, s in zip(hits, scores):
        norm = (s - lo) / (hi - lo) if hi > lo else 0.5
        h["rerank_score"] = round(float(s), 4)
        h["score"] = round(0.5 * h["score"] + 0.5 * norm, 4)
    return sorted(hits, key=lambda h: h["score"], reverse=True)


# ---------------------------------------------------------------- search

def _db_candidates(db: Session, user_id=None, video_id=None, label=None,
                   provider=None, start_seconds=None, end_seconds=None):
    q = db.query(Caption).join(Frame, Caption.frame_id == Frame.id)
    if user_id is not None:
        q = q.join(Video, Caption.video_id == Video.id).filter(Video.owner_id == user_id)
    if video_id:
        q = q.filter(Caption.video_id == video_id)
    if provider:
        q = q.filter(Caption.provider == provider)
    if start_seconds is not None:
        q = q.filter(Caption.timestamp_seconds >= start_seconds)
    if end_seconds is not None:
        q = q.filter(Caption.timestamp_seconds <= end_seconds)
    if label:
        q = q.join(Detection, Detection.frame_id == Frame.id).filter(Detection.label == label)
    return q.all()


def _score_caption(cap, qvec, query_terms, query_text, cos_override=None):
    frame = cap.frame
    emb = frame.embedding() if frame else None
    cos = cos_override if cos_override is not None else (cosine(qvec, emb) if emb else 0.0)
    labels = sorted({d.label for d in (frame.detections if frame else [])})
    kw = _keyword_score(query_terms, cap.text)
    label_hit = bool(set(labels) & query_terms)
    score = _hybrid_score(cos, kw, label_hit, query_text.lower() in cap.text.lower())
    return {"video_id": cap.video_id, "frame_id": cap.frame_id,
            "timestamp_seconds": cap.timestamp_seconds, "score": score,
            "caption": cap.text, "frame_path": frame.file_path if frame else None,
            "detections": labels, "provider": cap.provider}


def search_frames(db: Session, query: str, video_id=None, top_k: int = 10, min_score: float = 0.0,
                  user_id=None, label=None, provider=None, start_seconds=None,
                  end_seconds=None, rerank=None):
    """Search captions across videos. user_id scopes to that user's own
    videos (None = no scoping, used only by local stdio MCP use).
    Filters: detection label, caption provider, timestamp range, video.
    rerank=None follows settings.RERANKER_MODEL; pass True/False to
    force it on/off for a single call (the eval uses this for A/B)."""
    qvec, _ = embed(query)
    use_rerank = settings.RERANKER_MODEL != "" if rerank is None else rerank
    candidate_limit = top_k * 3 if use_rerank else top_k
    # The Qdrant path pre-selects by vector only, so it must fetch a
    # generous candidate pool: with weak (hash) embeddings the correct
    # frame is often outside the top-k by vector alone, and keyword
    # scoring (which runs after) can never rescue a frame Qdrant
    # never returned. 100 covers the whole small corpus; the hybrid
    # score and rerank then choose among all of them.
    qdrant_limit = max(100, candidate_limit)

    scored = []
    qdrant_configured = bool(settings.QDRANT_URL)
    if qdrant_configured:
        try:
            points = qdrant_search(
                qvec, top_k=qdrant_limit,
                user_id=user_id, video_id=video_id, label=label,
                provider=provider, start_seconds=start_seconds,
                end_seconds=end_seconds)
            frame_ids = [p.id for p in points]
            caps = (db.query(Caption).filter(Caption.frame_id.in_(frame_ids)).all()
                    if frame_ids else [])
            by_frame = {c.frame_id: c for c in caps}
            all_labels = set()
            for c in caps:
                if c.frame:
                    all_labels |= {d.label for d in c.frame.detections}
            query_terms = expand_query_terms(query, all_labels)
            for p in points:
                cap = by_frame.get(p.id)
                if cap is None:
                    continue  # Qdrant point with no DB caption: skip, don't invent
                scored.append(_score_caption(cap, qvec, query_terms, query,
                                             cos_override=float(p.score)))
        except Exception as exc:
            # Qdrant is an accelerator, not the source of truth: log
            # and fall back to the DB scan instead of failing search.
            logger.warning("qdrant search failed, falling back to DB scan: %s", exc)
            scored = []
    if not scored:
        # No Qdrant, Qdrant errored, or Qdrant returned no usable
        # points (empty or drifted index — e.g. a fresh in-memory
        # client, or a restarted server with a wiped volume). The DB
        # scan is the source of truth, so it runs as the safety net;
        # a Qdrant that misses hits the DB finds is drift, not a
        # correct empty answer.
        caps = _db_candidates(db, user_id, video_id, label, provider,
                              start_seconds, end_seconds)
        all_labels = set()
        for c in caps:
            if c.frame:
                all_labels |= {d.label for d in c.frame.detections}
        query_terms = expand_query_terms(query, all_labels)
        for cap in caps:
            scored.append(_score_caption(cap, qvec, query_terms, query))
        if qdrant_configured and scored:
            logger.warning(
                "qdrant returned no usable points but the DB scan found %d "
                "hit(s) — the vector index may be stale; run "
                "scripts/reindex_qdrant.py", len(scored))

    scored = [h for h in scored if h["score"] >= min_score]
    scored.sort(key=lambda h: h["score"], reverse=True)
    if use_rerank:
        scored = rerank_hits(query, scored[:candidate_limit])
    scored = compress_hits(scored)
    return scored[:top_k]
