"""Agentic orchestration (Phase 5): a deterministic multi-step
planner over 8 tools. The planner picks tools by intent keywords,
never by free-form LLM output; a question matching several tools
runs them in a fixed order (at most 3) and combines the results.
Single-tool questions behave exactly as before.

Framework decision (ADR 0001): this is deliberately NOT LangGraph.
The tools are deterministic functions, state already persists in
the conversations/messages tables, and no LLM tool-calling loop
is needed — a 3-node LangGraph graph would add a dependency and
its version churn for no capability. If a future tool needs
free-form LLM planning, revisit the ADR.

Conversational memory lives in the conversations/messages tables and
is passed back as prior turns. When an LLM provider is configured,
Q&A is synthesised from retrieved captions only; otherwise a
template answer quotes the retrieved captions with timestamps.
Empty retrieval is reported as such, never filled in.
"""
from collections import Counter

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Caption, Detection, Event, Frame, Scene, Video
from ..security import video_visible_to
from .detection import build_trajectories
from .retrieval import search_frames, validate_citations
from .summarization import summarize_video


def _llm_synthesize(question: str, evidence: list[dict],
                    history: list[dict] | None = None) -> str | None:
    """Phase 8 (M12): `history` is the prior turns of this
    conversation (role/content, oldest first). It goes into the
    prompt so follow-ups ("what colour was it?") resolve against
    what was already said — the evidence rule is unchanged: the
    answer must still come from the retrieved captions, and the
    model is told to say so when they do not answer it."""
    if settings.VLM_PROVIDER not in ("openai_compatible", "nvidia_nim") or not settings.VLM_BASE_URL:
        return None
    context = "\n".join(f"[{h['timestamp_seconds']:.1f}s] {h['caption']}" for h in evidence)
    prompt = ("Answer ONLY from the evidence below. Cite timestamps like [12.0s]. "
              "If the evidence does not answer the question, say so.\n\n"
              f"Evidence:\n{context}\n\n")
    if history:
        turns = "\n".join(f"{h['role']}: {h['content']}" for h in history)
        prompt += (f"Previous conversation (for context only — the answer "
                   f"must still come from the evidence above):\n{turns}\n\n")
    prompt += f"Question: {question}"
    try:
        headers = {"Content-Type": "application/json"}
        if settings.VLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.VLM_API_KEY}"
        # trust_env=False: httpx chokes on bracketed IPv6 entries in
        # this VM's NO_PROXY list (audit M3 — this call previously had
        # no workaround, unlike the Qdrant and reranker clients).
        with httpx.Client(trust_env=False, timeout=120) as client:
            r = client.post(f"{settings.VLM_BASE_URL.rstrip('/')}/chat/completions",
                            json={"model": settings.VLM_MODEL or "llm",
                                  "messages": [{"role": "user", "content": prompt}],
                                  "max_tokens": 500},
                            headers=headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


# ---------------------------------------------------------------- tools

def _visible_video(db: Session, video_id, user_id):
    video = db.get(Video, int(video_id)) if video_id else None
    if not video:
        return None
    if user_id is not None and video.owner_id != user_id:
        # Admins pass user_id=None and see all; anyone else must own it.
        return None
    return video


def detection_analytics(db: Session, video_id, user_id=None) -> dict:
    """Counts by label, distinct tracks, and dwell stats for a video."""
    video = _visible_video(db, video_id, user_id)
    if not video:
        return {"error": "Video not found"}
    dets = db.query(Detection).filter_by(video_id=video.id).all()
    counts = Counter(d.label for d in dets)
    rows = [{"track_id": d.track_id, "label": d.label,
             "timestamp_seconds": d.timestamp_seconds,
             "x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2} for d in dets]
    trajs = build_trajectories(rows)
    dwells = [t["dwell_seconds"] for t in trajs]
    return {"video_id": video.id, "title": video.title,
            "detection_count": len(dets),
            "detections_by_label": dict(counts),
            "top_labels": [{"label": label, "count": n}
                           for label, n in counts.most_common(5)],
            "track_count": len(trajs),
            "longest_dwell_seconds": max(dwells) if dwells else 0.0,
            "mean_dwell_seconds": round(sum(dwells) / len(dwells), 2) if dwells else 0.0,
            "trajectories": trajs}


def timeline_analysis(db: Session, video_id, user_id=None) -> dict:
    """Scene-by-scene timeline: time ranges, captions, detections."""
    video = _visible_video(db, video_id, user_id)
    if not video:
        return {"error": "Video not found"}
    scenes = (db.query(Scene).filter_by(video_id=video.id)
              .order_by(Scene.index).all())
    timeline = []
    for s in scenes:
        frames = (db.query(Frame).filter_by(video_id=video.id)
                  .filter(Frame.timestamp_seconds >= s.start_seconds,
                          Frame.timestamp_seconds <= s.end_seconds)
                  .order_by(Frame.timestamp_seconds).all())
        caps = [c.text for f in frames
                for c in db.query(Caption).filter_by(frame_id=f.id).all()]
        labels = sorted({d.label for f in frames for d in f.detections})
        timeline.append({"scene_index": s.index,
                         "start_seconds": s.start_seconds,
                         "end_seconds": s.end_seconds,
                         "captions": caps, "detections": labels})
    return {"video_id": video.id, "title": video.title,
            "duration_seconds": video.duration_seconds,
            "scene_count": len(scenes), "timeline": timeline}


def generate_report(db: Session, video_id, user_id=None, kind: str = "summary",
                    format: str = "json") -> dict:
    """Generate a report file for a video (same record the /reports
    endpoint creates) and return its id and download URL."""
    video = _visible_video(db, video_id, user_id)
    if not video:
        return {"error": "Video not found"}
    if kind not in ("summary", "incident", "timeline") or format not in ("json", "pdf"):
        return {"error": "Invalid kind or format (kind: summary|incident|timeline, "
                         "format: json|pdf)"}
    from . import reports as reports_svc

    owner_id = user_id if user_id is not None else video.owner_id
    result = reports_svc.create_report_record(db, video, owner_id, kind, format,
                                              settings.STORAGE_DIR)
    return {"report_id": result["id"], "video_id": video.id, "kind": kind,
            "format": format, "download_url": result["download_url"],
            "summary": (result["data"]["summary"] or "")[:500]}


def run_tool(name: str, db: Session, args: dict, user_id=None):
    """Single entry point for every tool, shared by the agent planner
    and the MCP server so the two can never drift apart. user_id=None
    means unscoped (admin / local stdio use); otherwise the caller
    only ever sees their own videos."""
    args = args or {}
    if name == "video_search":
        return search_frames(db, args["query"], video_id=args.get("video_id"),
                             top_k=int(args.get("top_k", 10)), user_id=user_id)
    if name == "video_qa":
        return answer_question(db, args["question"], video_id=args.get("video_id"),
                               user_id=user_id)
    if name == "video_summarize":
        video = _visible_video(db, args.get("video_id"), user_id)
        if not video:
            return {"error": "Video not found"}
        return summarize_video(db, video.id, length=args.get("length", "medium"))
    if name == "clip_retrieval":
        hits = search_frames(db, args["query"], video_id=args.get("video_id"),
                             top_k=5, user_id=user_id)
        hits = validate_citations(db, hits)
        return [{"video_id": h["video_id"],
                 "start_seconds": max(0.0, h["timestamp_seconds"] - 2),
                 "end_seconds": h["timestamp_seconds"] + 2,
                 "caption": h["caption"]} for h in hits]
    if name == "event_analysis":
        q = db.query(Event)
        if user_id is not None:
            q = q.join(Video, Event.video_id == Video.id).filter(Video.owner_id == user_id)
        if args.get("video_id"):
            q = q.filter_by(video_id=int(args["video_id"]))
        return [{"timestamp_seconds": e.timestamp_seconds, "title": e.title,
                 "severity": e.severity, "verified": e.verified}
                for e in q.order_by(Event.timestamp_seconds).limit(50).all()]
    if name == "detection_analytics":
        return detection_analytics(db, args.get("video_id"), user_id)
    if name == "timeline_analysis":
        return timeline_analysis(db, args.get("video_id"), user_id)
    if name == "report_generation":
        return generate_report(db, args.get("video_id"), user_id,
                               kind=args.get("kind", "summary"),
                               format=args.get("format", "json"))
    raise ValueError(f"Unknown tool: {name}")


# MCP-style tool registry: the same tools the agent uses are exposed
# over HTTP by mcp_server/ and listed by GET /api/v1/agent/tools.
TOOLS = [
    {"name": "video_search",
     "description": "Semantic search over processed video frames with timestamps",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "video_id": {"type": "integer"},
                                    "top_k": {"type": "integer"}},
                     "required": ["query"]}},
    {"name": "video_qa",
     "description": "Evidence-grounded question answering over video captions",
     "inputSchema": {"type": "object",
                     "properties": {"question": {"type": "string"},
                                    "video_id": {"type": "integer"}},
                     "required": ["question"]}},
    {"name": "video_summarize",
     "description": "Hierarchical chronological summary of a video",
     "inputSchema": {"type": "object",
                     "properties": {"video_id": {"type": "integer"},
                                    "length": {"type": "string",
                                               "enum": ["short", "medium", "long"]}},
                     "required": ["video_id"]}},
    {"name": "clip_retrieval",
     "description": "Retrieve clips (start/end timestamps) matching a query",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "video_id": {"type": "integer"}},
                     "required": ["query"]}},
    {"name": "event_analysis",
     "description": "List events and alerts for a video",
     "inputSchema": {"type": "object",
                     "properties": {"video_id": {"type": "integer"}},
                     "required": []}},
    {"name": "detection_analytics",
     "description": "Detection counts by label, track count and dwell stats for a video",
     "inputSchema": {"type": "object",
                     "properties": {"video_id": {"type": "integer"}},
                     "required": ["video_id"]}},
    {"name": "timeline_analysis",
     "description": "Scene-by-scene timeline with captions and detections",
     "inputSchema": {"type": "object",
                     "properties": {"video_id": {"type": "integer"}},
                     "required": ["video_id"]}},
    {"name": "report_generation",
     "description": "Generate a JSON or PDF report for a video",
     "inputSchema": {"type": "object",
                     "properties": {"video_id": {"type": "integer"},
                                    "kind": {"type": "string",
                                             "enum": ["summary", "incident", "timeline"]},
                                    "format": {"type": "string",
                                               "enum": ["json", "pdf"]}},
                     "required": ["video_id"]}},
]


# ---------------------------------------------------------------- planning

# Fixed execution order for multi-tool questions: summaries and
# timelines first (they frame the answer), reports last (they bundle
# everything). At most 3 tools run for one question.
_TOOL_ORDER = ["video_summarize", "timeline_analysis", "detection_analytics",
               "event_analysis", "clip_retrieval", "report_generation", "video_qa"]


def _plan(question: str) -> list[str]:
    """Deterministic intent routing: keyword match, never free-form
    LLM output. Returns 1 tool for a simple question, up to 3 for a
    question that asks for several things at once."""
    q = question.lower()
    wanted = set()
    if "summar" in q:
        wanted.add("video_summarize")
    if "timeline" in q:
        wanted.add("timeline_analysis")
    if any(w in q for w in ("detect", "analytics", "track", "dwell",
                          "how many detections", "how many tracks",
                          "count the detections")):
        wanted.add("detection_analytics")
    if any(w in q for w in ("event", "alert", "incident")):
        wanted.add("event_analysis")
    if "clip" in q:
        wanted.add("clip_retrieval")
    if "report" in q:
        wanted.add("report_generation")
    if not wanted:
        wanted.add("video_qa")
    return [t for t in _TOOL_ORDER if t in wanted][:3]


def answer_question(db: Session, question: str, video_id=None, user_id=None,
                    history: list[dict] | None = None) -> dict:
    """Evidence-grounded Q&A. user_id scopes retrieval to that user's own
    videos (None = no scoping, used only by local stdio MCP use); the
    chat endpoint passes the logged-in user, admins pass None.
    `history` (Phase 8 / M12) is the conversation's prior turns, used
    only by the LLM synthesis step — retrieval itself stays evidence
    based, never on memory alone."""
    plan = _plan(question)
    if len(plan) == 1 and plan[0] == "video_qa":
        return _answer_qa(db, question, video_id, user_id, history)
    if len(plan) == 1:
        return _answer_single(db, plan[0], question, video_id, user_id)
    # Multi-step: run each tool, combine the sections, merge and
    # validate the citations once at the end.
    sections, citations, tools_used = [], [], []
    for tool in plan:
        result = _answer_single(db, tool, question, video_id, user_id)
        tools_used.append(tool)
        sections.append(f"## {tool}\n{result['answer']}")
        citations.extend(result.get("citations") or [])
    citations = validate_citations(db, citations)
    return {"answer": "\n\n".join(sections), "citations": citations,
            "tool": "multi_step", "steps": tools_used, "confidence": "medium"}


def _answer_single(db: Session, tool: str, question: str, video_id, user_id) -> dict:
    """One planned tool, in the agent's answer shape."""
    if tool == "video_summarize":
        if not video_id:
            return {"answer": "Please specify a video_id to summarise.",
                    "citations": [], "tool": "summarize", "confidence": "low"}
        s = summarize_video(db, video_id, length="medium")
        cites = [{"video_id": video_id, "timestamp_seconds": t["start_seconds"],
                  "text": t["text"][:200]} for t in s["timeline"]]
        return {"answer": s["summary"], "citations": cites, "tool": "summarize",
                "confidence": "medium" if s["scene_count"] else "low"}
    if tool == "timeline_analysis":
        if not video_id:
            return {"answer": "Please specify a video_id for the timeline.",
                    "citations": [], "tool": "timeline", "confidence": "low"}
        t = timeline_analysis(db, video_id, user_id)
        if "error" in t:
            return {"answer": "Video not found.", "citations": [],
                    "tool": "timeline", "confidence": "low"}
        lines = [f"{s['start_seconds']:.1f}s–{s['end_seconds']:.1f}s: "
                 f"{'; '.join(s['captions']) or '(no caption)'} "
                 f"[{', '.join(s['detections']) or 'no detections'}]"
                 for s in t["timeline"]]
        cites = [{"video_id": video_id, "timestamp_seconds": s["start_seconds"],
                  "text": (s["captions"][0][:200] if s["captions"] else "")}
                 for s in t["timeline"]]
        return {"answer": "Timeline:\n" + "\n".join(lines), "citations": cites,
                "tool": "timeline", "confidence": "medium"}
    if tool == "detection_analytics":
        if not video_id:
            return {"answer": "Please specify a video_id for detection analytics.",
                    "citations": [], "tool": "detection_analytics", "confidence": "low"}
        d = detection_analytics(db, video_id, user_id)
        if "error" in d:
            return {"answer": "Video not found.", "citations": [],
                    "tool": "detection_analytics", "confidence": "low"}
        labels = ", ".join(f"{x['label']} ({x['count']})" for x in d["top_labels"])
        return {"answer": (f"{d['detection_count']} detections across "
                           f"{d['track_count']} tracks. By label: {labels or 'none'}. "
                           f"Longest dwell {d['longest_dwell_seconds']:.1f}s, "
                           f"mean dwell {d['mean_dwell_seconds']:.1f}s."),
                "citations": [], "tool": "detection_analytics", "confidence": "high"}
    if tool == "event_analysis":
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
    if tool == "clip_retrieval":
        hits = search_frames(db, question, video_id=video_id, top_k=5, user_id=user_id)
        hits = validate_citations(db, hits)
        clips = [{"video_id": h["video_id"], "start_seconds": max(0.0, h["timestamp_seconds"] - 2),
                  "end_seconds": h["timestamp_seconds"] + 2, "caption": h["caption"]} for h in hits]
        return {"answer": f"Found {len(clips)} clip(s) matching the query.",
                "citations": hits, "clips": clips, "tool": "clips", "confidence": "medium"}
    if tool == "report_generation":
        if not video_id:
            return {"answer": "Please specify a video_id for the report.",
                    "citations": [], "tool": "report", "confidence": "low"}
        r = generate_report(db, video_id, user_id)
        if "error" in r:
            return {"answer": r["error"], "citations": [],
                    "tool": "report", "confidence": "low"}
        return {"answer": (f"Report {r['report_id']} generated "
                           f"({r['kind']}, {r['format']}). Download: {r['download_url']}"),
                "citations": [], "tool": "report", "confidence": "high",
                "report_id": r["report_id"], "download_url": r["download_url"]}
    return _answer_qa(db, question, video_id, user_id)


def _answer_qa(db: Session, question: str, video_id, user_id,
               history: list[dict] | None = None) -> dict:
    # Agent Q&A uses a stricter floor than the raw search API: hash
    # embeddings score unrelated text around 0.30, so <0.45 means "no
    # evidence" rather than a confident-sounding guess. (Phase 4
    # finding: this floor is tuned for hash embeddings; with
    # FastEmbed it admits false evidence — per-provider calibration
    # is an open follow-up, not tuned to the eval set.)
    # Phase 8 (M12): a follow-up like "what colour is it?" carries
    # almost no retrieval signal on its own. When the conversation
    # has a previous user question, search with that question prepended
    # so the follow-up retrieves the same evidence its antecedent did.
    # The evidence floor and the "no evidence" answer are unchanged.
    query = question
    if history:
        prev_user = [h["content"] for h in history if h["role"] == "user"]
        if prev_user:
            query = prev_user[-1] + " " + question
    hits = search_frames(db, query, video_id=video_id, top_k=5, min_score=0.45, user_id=user_id)
    # Phase 4: never cite a frame that does not exist in the DB.
    hits = validate_citations(db, hits)
    if not hits:
        return {"answer": "No video evidence was retrieved for this question, so I cannot answer "
                "it from the video library. Try a different query or process more video.",
                "citations": [], "tool": "search_qa", "confidence": "low"}
    llm = _llm_synthesize(question, hits, history)
    if llm:
        answer = llm
    else:
        evidence = "\n".join(f"[{h['timestamp_seconds']:.1f}s] {h['caption']}" for h in hits)
        answer = (f"Based on the retrieved video evidence:\n{evidence}\n\n"
                  f"Answer: the moments above are the closest matches in the video "
                  f"for '{question}'. See the timestamp citations for the source frames.")
    return {"answer": answer, "citations": hits, "tool": "search_qa", "confidence": "medium"}
