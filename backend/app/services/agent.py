"""Agentic orchestration (LangGraph-shaped, dependency-light).

The orchestrator picks tools by intent, never by free-form LLM output:
- 'summar' in the question -> summarize tool
- 'event'/'alert'/'incident' -> events tool
- 'clip' -> clip retrieval tool
- otherwise -> search + evidence-grounded Q&A tool

Conversational memory lives in the conversations/messages tables and is
passed back as prior turns. When an LLM provider is configured, Q&A is
synthesised from retrieved captions only; otherwise a template answer
quotes the retrieved captions with timestamps. Empty retrieval is
reported as such, never filled in.
"""
import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Event, Video
from .retrieval import search_frames, validate_citations
from .summarization import summarize_video


def _llm_synthesize(question: str, evidence: list[dict]) -> str | None:
    if settings.VLM_PROVIDER not in ("openai_compatible", "nvidia_nim") or not settings.VLM_BASE_URL:
        return None
    context = "\n".join(f"[{h['timestamp_seconds']:.1f}s] {h['caption']}" for h in evidence)
    prompt = ("Answer ONLY from the evidence below. Cite timestamps like [12.0s]. "
              "If the evidence does not answer the question, say so.\n\n"
              f"Evidence:\n{context}\n\nQuestion: {question}")
    try:
        headers = {"Content-Type": "application/json"}
        if settings.VLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VLM_API_KEY}"
        r = httpx.post(f"{settings.VLM_BASE_URL.rstrip('/')}/chat/completions",
                       json={"model": settings.VLM_MODEL or "llm",
                             "messages": [{"role": "user", "content": prompt}], "max_tokens": 500},
                       headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def answer_question(db: Session, question: str, video_id=None, user_id=None) -> dict:
    """Evidence-grounded Q&A. user_id scopes retrieval to that user's own
    videos (None = no scoping, used only by local stdio MCP use); the
    chat endpoint passes the logged-in user, admins pass None."""
    q = question.lower()
    if "summar" in q:
        if not video_id:
            return {"answer": "Please specify a video_id to summarise.",
                    "citations": [], "tool": "summarize", "confidence": "low"}
        s = summarize_video(db, video_id, length="medium")
        cites = [{"video_id": video_id, "timestamp_seconds": t["start_seconds"],
                  "text": t["text"][:200]} for t in s["timeline"]]
        return {"answer": s["summary"], "citations": cites, "tool": "summarize",
                "confidence": "medium" if s["scene_count"] else "low"}
    if any(w in q for w in ("event", "alert", "incident")):
        query = db.query(Event)
        if user_id is not None:
            query = query.join(Video, Event.video_id == Video.id).filter(Video.owner_id == user_id)
        if video_id:
            query = query.filter_by(video_id=video_id)
        events = query.order_by(Event.timestamp_seconds).limit(20).all()
        if not events:
            return {"answer": "No events have been recorded for this video.",
                    "citations": [], "tool": "events", "confidence": "high"}
        lines = [f"{e.timestamp_seconds:.1f}s — {e.title} [{e.severity}] verified={e.verified}"
                 for e in events]
        cites = [{"video_id": e.video_id, "timestamp_seconds": e.timestamp_seconds, "text": e.title}
                 for e in events]
        return {"answer": "Events found:\n" + "\n".join(lines), "citations": cites,
                "tool": "events", "confidence": "high"}
    if "clip" in q:
        hits = search_frames(db, question, video_id=video_id, top_k=5, user_id=user_id)
        hits = validate_citations(db, hits)
        clips = [{"video_id": h["video_id"], "start_seconds": max(0.0, h["timestamp_seconds"] - 2),
                  "end_seconds": h["timestamp_seconds"] + 2, "caption": h["caption"]} for h in hits]
        return {"answer": f"Found {len(clips)} clip(s) matching the query.",
                "citations": hits, "clips": clips, "tool": "clips", "confidence": "medium"}
    # Agent Q&A uses a stricter floor than the raw search API: hash
    # embeddings score unrelated text around 0.30, so <0.45 means "no
    # evidence" rather than a confident-sounding guess.
    hits = search_frames(db, question, video_id=video_id, top_k=5, min_score=0.45, user_id=user_id)
    # Phase 4: never cite a frame that does not exist in the DB.
    hits = validate_citations(db, hits)
    if not hits:
        return {"answer": "No video evidence was retrieved for this question, so I cannot answer "
                "it from the video library. Try a different query or process more video.",
                "citations": [], "tool": "search_qa", "confidence": "low"}
    llm = _llm_synthesize(question, hits)
    if llm:
        answer = llm
    else:
        evidence = "\n".join(f"[{h['timestamp_seconds']:.1f}s] {h['caption']}" for h in hits)
        answer = (f"Based on the retrieved video evidence:\n{evidence}\n\n"
                  f"Answer: the moments above are the closest matches in the video "
                  f"for '{question}'. See the timestamp citations for the source frames.")
    return {"answer": answer, "citations": hits, "tool": "search_qa", "confidence": "medium"}


# MCP-style tool registry: the same tools the agent uses are exposed over
# HTTP by mcp_server/ and listed by GET /api/v1/agent/tools.
TOOLS = [
    {"name": "video_search", "description": "Semantic search over processed video frames with timestamps"},
    {"name": "video_qa", "description": "Evidence-grounded question answering over video captions"},
    {"name": "video_summarize", "description": "Hierarchical chronological summary of a video"},
    {"name": "clip_retrieval", "description": "Retrieve clips (start/end timestamps) matching a query"},
    {"name": "event_analysis", "description": "List events and alerts for a video"},
]
