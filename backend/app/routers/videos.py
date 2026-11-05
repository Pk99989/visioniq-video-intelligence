import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Alert, Caption, Event, Frame, ProcessingJob, Scene, User, Video
from ..schemas import EventRuleIn, VideoOut
from ..security import get_current_user, video_visible_to
from ..services import events as events_svc
from ..services import worker

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


def _get_video(db: Session, video_id: int, user: User) -> Video:
    video = db.get(Video, video_id)
    if not video or not video_visible_to(video, user):
        raise HTTPException(404, "Video not found")
    return video


@router.post("/upload", response_model=VideoOut, status_code=201)
def upload_video(background: BackgroundTasks, title: str = Form(...), file: UploadFile = File(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format '.{ext}'. Allowed: {sorted(settings.ALLOWED_EXTENSIONS)}")
    # Stream to disk with a hard size cap (never trust Content-Length alone).
    video = Video(owner_id=user.id, title=title, original_filename=file.filename,
                  file_path="", file_size_bytes=0)
    db.add(video)
    db.flush()
    vdir = settings.STORAGE_DIR / "videos" / str(video.id)
    vdir.mkdir(parents=True, exist_ok=True)
    dest = vdir / f"original.{ext}"
    size = 0
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                dest.unlink(missing_ok=True)
                db.rollback()
                raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB} MB limit")
            out.write(chunk)
    video.file_path, video.file_size_bytes = str(dest), size
    db.add(ProcessingJob(video_id=video.id, status="queued"))
    db.commit()
    db.refresh(video)
    worker.dispatch(video.id, background)
    db.refresh(video)
    return video


@router.get("", response_model=list[VideoOut])
def list_videos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Video)
    if user.role != "admin":
        q = q.filter_by(owner_id=user.id)
    return q.order_by(Video.id.desc()).all()


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_video(db, video_id, user)


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_video(db, video_id, user)
    vdir = settings.STORAGE_DIR / "videos" / str(video_id)
    shutil.rmtree(vdir, ignore_errors=True)  # secure deletion: remove stored files too
    db.delete(video)
    db.commit()
    return None


@router.post("/{video_id}/retry", response_model=VideoOut)
def retry_video(background: BackgroundTasks, video_id: int,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_video(db, video_id, user)
    if video.status not in ("failed", "uploaded"):
        raise HTTPException(400, f"Cannot retry a video in status '{video.status}'")
    db.add(ProcessingJob(video_id=video.id, status="queued"))
    video.status = "uploaded"
    db.commit()
    worker.dispatch(video.id, background)
    db.refresh(video)
    return video


@router.get("/{video_id}/stream")
def stream_video(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_video(db, video_id, user)
    if not Path(video.file_path).exists():
        raise HTTPException(404, "Video file not found")
    ext = Path(video.file_path).suffix.lower()
    media = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
             "mkv": "video/x-matroska", "avi": "video/x-msvideo"}.get(ext.lstrip("."), "video/mp4")
    return FileResponse(video.file_path, media_type=media, filename=video.original_filename)


@router.get("/{video_id}/scenes")
def get_scenes(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    return [{"id": s.id, "index": s.index, "start_seconds": s.start_seconds, "end_seconds": s.end_seconds}
            for s in db.query(Scene).filter_by(video_id=video_id).order_by(Scene.index).all()]


@router.get("/{video_id}/frames")
def get_frames(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    frames = db.query(Frame).filter_by(video_id=video_id).order_by(Frame.timestamp_seconds).all()
    return [{"id": f.id, "timestamp_seconds": f.timestamp_seconds, "scene_id": f.scene_id,
             "image_url": f"/api/v1/videos/{video_id}/frames/{f.id}/image"} for f in frames]


@router.get("/{video_id}/frames/{frame_id}/image")
def get_frame_image(video_id: int, frame_id: int,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    frame = db.get(Frame, frame_id)
    if not frame or frame.video_id != video_id or not Path(frame.file_path).exists():
        raise HTTPException(404, "Frame not found")
    return FileResponse(frame.file_path, media_type="image/jpeg")


@router.get("/{video_id}/captions")
def get_captions(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    caps = db.query(Caption).filter_by(video_id=video_id).order_by(Caption.timestamp_seconds).all()
    return [{"id": c.id, "timestamp_seconds": c.timestamp_seconds, "text": c.text,
             "provider": c.provider, "frame_id": c.frame_id} for c in caps]


@router.post("/{video_id}/events/evaluate")
def evaluate_events(video_id: int, rules: list[EventRuleIn],
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    created = events_svc.evaluate_rules(db, video_id, [r.model_dump() for r in rules])
    return [{"id": e.id, "title": e.title, "timestamp_seconds": e.timestamp_seconds,
             "severity": e.severity, "verified": e.verified} for e in created]


@router.get("/{video_id}/events")
def get_events(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    evs = db.query(Event).filter_by(video_id=video_id).order_by(Event.timestamp_seconds).all()
    return [{"id": e.id, "rule_name": e.rule_name, "title": e.title, "severity": e.severity,
             "timestamp_seconds": e.timestamp_seconds, "verified": e.verified,
             "description": e.description} for e in evs]


@router.get("/{video_id}/alerts")
def get_alerts(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    alerts = db.query(Alert).filter_by(video_id=video_id).order_by(Alert.id.desc()).all()
    return [{"id": a.id, "event_id": a.event_id, "severity": a.severity, "message": a.message,
             "acknowledged": a.acknowledged} for a in alerts]


@router.post("/{video_id}/alerts/{alert_id}/acknowledge")
def acknowledge_alert(video_id: int, alert_id: int,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    alert = db.get(Alert, alert_id)
    if not alert or alert.video_id != video_id:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"id": alert.id, "acknowledged": True}
