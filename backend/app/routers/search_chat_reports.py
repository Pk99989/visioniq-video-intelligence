from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Conversation, Message, Report, User, Video
from ..schemas import ChatIn, ReportIn, SearchHit, SearchIn
from ..security import get_current_user, video_visible_to
from ..services import agent, reports as reports_svc
from ..services.retrieval import search_frames
from ..services.summarization import summarize_video

router = APIRouter(prefix="/api/v1", tags=["search-chat-reports"])


@router.post("/search", response_model=list[SearchHit])
def search(body: SearchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.video_id:
        video = db.get(Video, body.video_id)
        if not video or not video_visible_to(video, user):
            raise HTTPException(404, "Video not found")
    return search_frames(db, body.query, video_id=body.video_id,
                         top_k=body.top_k, min_score=body.min_score,
                         user_id=user.id if user.role != "admin" else None,
                         label=body.label, provider=body.provider,
                         start_seconds=body.start_seconds,
                         end_seconds=body.end_seconds, rerank=body.rerank)


@router.get("/agent/tools")
def agent_tools(user: User = Depends(get_current_user)):
    return agent.TOOLS


@router.get("/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dashboard analytics (Phase 8): owner-scoped totals. Admins see
    the whole system; everyone else sees only their own videos. All
    counts come from the DB — no video files are opened."""
    from sqlalchemy import func

    from ..models import Detection, Event, ProcessingJob

    scope = None if user.role == "admin" else user.id
    vq = db.query(Video)
    if scope is not None:
        vq = vq.filter_by(owner_id=scope)
    videos = vq.all()
    vids = [v.id for v in videos]
    dq = db.query(Detection)
    eq = db.query(Event)
    if vids:
        dq = dq.filter(Detection.video_id.in_(vids))
        eq = eq.filter(Event.video_id.in_(vids))
    else:
        dq = dq.filter(False)
        eq = eq.filter(False)
    by_label = (dq.with_entities(Detection.label, func.count())
                .group_by(Detection.label).order_by(func.count().desc())
                .limit(10).all())
    durations = []
    for job in db.query(ProcessingJob).filter_by(status="done").all():
        if vids and job.video_id not in vids:
            continue
        if job.updated_at and job.created_at:
            durations.append((job.updated_at - job.created_at).total_seconds())
    return {
        "videos_total": len(videos),
        "videos_ready": sum(1 for v in videos if v.status == "ready"),
        "videos_processing": sum(1 for v in videos if v.status in ("processing", "uploaded")),
        "videos_failed": sum(1 for v in videos if v.status == "failed"),
        "total_duration_seconds": round(sum(v.duration_seconds or 0 for v in videos), 1),
        "total_storage_bytes": sum(v.file_size_bytes or 0 for v in videos),
        "detections_total": dq.count(),
        "detections_by_label": [{"label": label, "count": n} for label, n in by_label],
        "events_total": eq.count(),
        "events_verified": eq.filter_by(verified=True).count(),
        "avg_processing_seconds": (round(sum(durations) / len(durations), 1)
                                   if durations else None),
        "jobs_timed": len(durations),
    }


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.video_id:
        video = db.get(Video, body.video_id)
        if not video or not video_visible_to(video, user):
            raise HTTPException(404, "Video not found")
    conv = None
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if not conv or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found")
    if not conv:
        conv = Conversation(user_id=user.id, video_id=body.video_id,
                            title=body.question[:80])
        db.add(conv)
        db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content=body.question))
    # M12: prior turns are passed to the agent so follow-ups ("what
    # colour was it?") are answered in context, not as standalone
    # questions. The just-added user message is prior[0] (newest
    # first), so prior[1:] is the previous turns, oldest first.
    prior = (db.query(Message).filter_by(conversation_id=conv.id)
             .order_by(Message.id.desc()).limit(7).all())
    history = [{"role": m.role, "content": m.content}
               for m in reversed(prior[1:])]
    result = agent.answer_question(db, body.question, video_id=body.video_id,
                                   user_id=user.id if user.role != "admin" else None,
                                   history=history)
    import json

    db.add(Message(conversation_id=conv.id, role="assistant", content=result["answer"],
                   citations_json=json.dumps(result.get("citations", []), default=str)))
    db.commit()
    return {"conversation_id": conv.id, **result}


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convs = db.query(Conversation).filter_by(user_id=user.id).order_by(Conversation.id.desc()).all()
    return [{"id": c.id, "title": c.title, "video_id": c.video_id} for c in convs]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return {"id": conv.id, "title": conv.title, "video_id": conv.video_id,
            "messages": [{"role": m.role, "content": m.content} for m in conv.messages]}


@router.get("/videos/{video_id}/summary")
def summary(video_id: int, length: str = "medium",
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video or not video_visible_to(video, user):
        raise HTTPException(404, "Video not found")
    return summarize_video(db, video_id, length=length)


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = db.get(Video, body.video_id)
    if not video or not video_visible_to(video, user):
        raise HTTPException(404, "Video not found")
    if body.kind not in ("summary", "incident", "timeline") or body.format not in ("json", "pdf"):
        raise HTTPException(400, "Invalid kind or format")
    data = reports_svc.build_report_data(db, video, body.kind)
    return reports_svc.create_report_record(db, video, user.id, body.kind,
                                            body.format, settings.STORAGE_DIR)


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report or (report.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Report not found")
    media = "application/pdf" if report.format == "pdf" else "application/json"
    return FileResponse(report.file_path, media_type=media, filename=Path(report.file_path).name)
