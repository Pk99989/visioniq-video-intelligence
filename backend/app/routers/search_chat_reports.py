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
                         top_k=body.top_k, min_score=body.min_score)


@router.get("/agent/tools")
def agent_tools(user: User = Depends(get_current_user)):
    return agent.TOOLS


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
    result = agent.answer_question(db, body.question, video_id=body.video_id)
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
    rdir = settings.STORAGE_DIR / "reports" / str(video.id)
    if body.format == "json":
        path = reports_svc.write_json_report(data, rdir / f"report_{body.kind}.json")
    else:
        path = reports_svc.write_pdf_report(data, rdir / f"report_{body.kind}.pdf")
    report = Report(video_id=video.id, owner_id=user.id, kind=body.kind,
                    file_path=str(path), format=body.format)
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "video_id": video.id, "kind": body.kind, "format": body.format,
            "download_url": f"/api/v1/reports/{report.id}/download", "data": data}


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report or (report.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Report not found")
    media = "application/pdf" if report.format == "pdf" else "application/json"
    return FileResponse(report.file_path, media_type=media, filename=Path(report.file_path).name)
