import logging
import re
import shutil
from collections import Counter
from pathlib import Path

logger = logging.getLogger("visioniq.videos")

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Alert, Caption, Detection, Event, Frame, ProcessingJob, Scene, User, Video, Zone
from ..schemas import EventRuleIn, VideoOut, ZoneIn
from ..security import create_stream_token, get_current_user, verify_stream_token, video_visible_to
from ..services import clips as clips_svc
from ..services import detection as detection_svc
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
    # Phase 9: magic-byte sniffing — the extension is user-controlled,
    # so the first bytes must match the container it claims to be.
    # mp4/mov: "....ftyp" at offset 4; webm/mkv: EBML header 1A 45 DF A3;
    # avi: "RIFF" + "AVI " at offset 8. A renamed .txt/.zip is rejected
    # before anything is written to disk.
    head = file.file.read(12)
    file.file.seek(0)
    _check_magic_bytes(ext, head)
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
    # Phase 9: optional virus scan hook (CLAMSCAN_CMD, e.g.
    # "clamscan --no-summary"). A non-zero exit rejects the upload
    # and deletes the file; empty command = no scan.
    if settings.CLAMSCAN_CMD:
        import shlex
        import subprocess

        try:
            proc = subprocess.run(shlex.split(settings.CLAMSCAN_CMD) + [str(dest)],
                                  capture_output=True, timeout=300)
        except Exception as e:  # noqa: BLE001 - a broken scanner must not keep a bad file
            proc = None
            logger.warning("virus scan failed to run on video %s: %s", video.id, e)
        if proc is not None and proc.returncode != 0:
            dest.unlink(missing_ok=True)
            db.delete(video)
            db.commit()
            raise HTTPException(400, "Upload rejected by the virus scan")
    db.add(ProcessingJob(video_id=video.id, status="queued"))
    db.commit()
    db.refresh(video)
    # Phase 10: the upload request's id travels with the job so the
    # pipeline's log lines can be traced back to this request.
    from ..services.logging_config import get_request_id

    worker.dispatch(video.id, background, request_id=get_request_id())
    db.refresh(video)
    return video


def _check_magic_bytes(ext: str, head: bytes) -> None:
    """Phase 9: reject files whose first bytes don't match the claimed
    container. Raises 400 on mismatch or on a file too short to check."""
    ok = False
    if ext in ("mp4", "mov"):
        ok = len(head) >= 8 and head[4:8] == b"ftyp"
    elif ext in ("webm", "mkv"):
        ok = head[:4] == b"\x1a\x45\xdf\xa3"
    elif ext == "avi":
        ok = len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI "
    if not ok:
        raise HTTPException(
            400, f"File content does not match the '.{ext}' container "
                 "(magic bytes check failed) — the file may be misnamed")


@router.get("", response_model=list[VideoOut])
def list_videos(response: Response, user: User = Depends(get_current_user),
                db: Session = Depends(get_db),
                limit: int = Query(50, ge=1, le=100),
                offset: int = Query(0, ge=0)):
    """Paginated (Phase 8 / L10): the list shape is unchanged, the
    total goes in X-Total-Count so the frontend can page without a
    second request."""
    q = db.query(Video)
    if user.role != "admin":
        q = q.filter_by(owner_id=user.id)
    response.headers["X-Total-Count"] = str(q.count())
    return q.order_by(Video.id.desc()).offset(offset).limit(limit).all()


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
    from ..services.logging_config import get_request_id

    worker.dispatch(video.id, background, request_id=get_request_id())
    db.refresh(video)
    return video


def _auth_for_stream(request: Request, video_id: int, db: Session) -> User:
    """Stream auth: bearer token (API clients) OR a short-lived signed
    ?token= (the <video> tag, which cannot send headers)."""
    token = request.query_params.get("token")
    if token:
        verified = verify_stream_token(token)
        if not verified or verified[1] != video_id:
            raise HTTPException(401, "Invalid or expired stream token")
        user = db.get(User, verified[0])
        if not user:
            raise HTTPException(401, "User not found")
        return user
    return _bearer_user(request, db)


def _bearer_user(request: Request, db: Session) -> User:
    from ..security import decode_token, is_revoked

    auth = request.headers.get("Authorization", "")
    raw = auth.removeprefix("Bearer ").strip()
    data = decode_token(raw) if raw else None
    if not data or is_revoked(db, data.get("jti")):
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(data["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    return user


@router.get("/{video_id}/stream-url")
def stream_url(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return a signed URL the <video> tag can use directly (5 min).
    This is what makes HTTP Range seeking work in the browser."""
    _get_video(db, video_id, user)
    token = create_stream_token(user, video_id)
    return {"url": f"/api/v1/videos/{video_id}/stream?token={token}", "expires_in_seconds": 300}


@router.get("/{video_id}/stream")
def stream_video(request: Request, video_id: int, db: Session = Depends(get_db)):
    user = _auth_for_stream(request, video_id, db)
    video = _get_video(db, video_id, user)
    path = Path(video.file_path)
    if not path.exists():
        raise HTTPException(404, "Video file not found")
    ext = path.suffix.lower()
    media = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
             "mkv": "video/x-matroska", "avi": "video/x-msvideo"}.get(ext.lstrip("."), "video/mp4")
    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media, filename=video.original_filename)
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        raise HTTPException(416, "Invalid Range header")
    start_s, end_s = m.groups()
    start = int(start_s) if start_s else size - int(end_s) if end_s else 0
    end = int(end_s) if end_s else size - 1
    if start < 0 or start >= size or end < start:
        raise HTTPException(416, "Requested Range Not Satisfiable")
    end = min(end, size - 1)

    def _iter():
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(_iter(), status_code=206, media_type=media, headers={
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    })


@router.get("/{video_id}/clip")
def download_clip(video_id: int, start: float = Query(..., ge=0),
                  end: float = Query(..., gt=0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Download a [start, end] clip of a processed video as an mp4."""
    video = _get_video(db, video_id, user)
    if video.duration_seconds and end > video.duration_seconds:
        raise HTTPException(400, f"end {end}s is past the video duration {video.duration_seconds}s")
    if end <= start or end - start > 120:
        raise HTTPException(400, "Clip must be 0-120 seconds long and end after start")
    try:
        clip_path = clips_svc.extract_clip(Path(video.file_path), video.id, start, end)
    except Exception as e:  # noqa: BLE001 - ffmpeg failure
        raise HTTPException(500, f"Clip extraction failed: {e}")
    return FileResponse(clip_path, media_type="video/mp4",
                        filename=f"clip_{video.id}_{start:.1f}-{end:.1f}.mp4")


@router.get("/{video_id}/detections")
def get_detections(video_id: int, response: Response, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0)):
    _get_video(db, video_id, user)
    q = db.query(Detection).filter_by(video_id=video_id).order_by(Detection.timestamp_seconds)
    response.headers["X-Total-Count"] = str(q.count())
    dets = q.offset(offset).limit(limit).all()
    return [{"id": d.id, "frame_id": d.frame_id, "track_id": d.track_id, "label": d.label,
             "confidence": round(d.confidence, 3), "timestamp_seconds": d.timestamp_seconds,
             "x1": round(d.x1, 1), "y1": round(d.y1, 1), "x2": round(d.x2, 1), "y2": round(d.y2, 1)}
            for d in dets]


@router.get("/{video_id}/trajectories")
def get_trajectories(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Object trajectories (Phase 3): one entry per track id — label,
    first/last seen, dwell time (last − first), frames seen, total
    displacement, and the centre-point path. Built from stored
    detections, so it works for any already-processed video. Owner-
    scoped like every other video route."""
    from ..services.detection import build_trajectories

    _get_video(db, video_id, user)
    dets = db.query(Detection).filter_by(video_id=video_id).order_by(Detection.timestamp_seconds).all()
    rows = [{"track_id": d.track_id, "label": d.label, "timestamp_seconds": d.timestamp_seconds,
             "x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2} for d in dets]
    return build_trajectories(rows)


@router.get("/{video_id}/analytics")
def get_analytics(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_video(db, video_id, user)
    dets = db.query(Detection).filter_by(video_id=video_id).all()
    counts = Counter(d.label for d in dets)
    return {"video_id": video.id, "title": video.title, "status": video.status,
            "duration_seconds": video.duration_seconds,
            "scene_count": db.query(Scene).filter_by(video_id=video_id).count(),
            "frame_count": db.query(Frame).filter_by(video_id=video_id).count(),
            "caption_count": db.query(Caption).filter_by(video_id=video_id).count(),
            "detection_count": len(dets),
            "detections_by_label": dict(counts),
            "top_labels": [{"label": label, "count": n} for label, n in counts.most_common(5)]}


@router.get("/{video_id}/scenes")
def get_scenes(video_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    return [{"id": s.id, "index": s.index, "start_seconds": s.start_seconds, "end_seconds": s.end_seconds}
            for s in db.query(Scene).filter_by(video_id=video_id).order_by(Scene.index).all()]


@router.get("/{video_id}/frames")
def get_frames(video_id: int, response: Response, user: User = Depends(get_current_user),
               db: Session = Depends(get_db),
               limit: int = Query(100, ge=1, le=500),
               offset: int = Query(0, ge=0)):
    _get_video(db, video_id, user)
    q = db.query(Frame).filter_by(video_id=video_id).order_by(Frame.timestamp_seconds)
    response.headers["X-Total-Count"] = str(q.count())
    frames = q.offset(offset).limit(limit).all()
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


@router.get("/{video_id}/frames/{frame_id}/annotated")
def get_frame_annotated(video_id: int, frame_id: int,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The frame image with YOLO boxes drawn on it (cached on disk)."""
    _get_video(db, video_id, user)
    frame = db.get(Frame, frame_id)
    if not frame or frame.video_id != video_id or not Path(frame.file_path).exists():
        raise HTTPException(404, "Frame not found")
    dets = db.query(Detection).filter_by(frame_id=frame_id).all()
    out = Path(frame.file_path).parent / f"annotated_{frame_id}.jpg"
    if not out.exists():
        detection_svc.annotate_frame(frame.file_path,
            [{"label": d.label, "confidence": d.confidence, "x1": d.x1, "y1": d.y1,
              "x2": d.x2, "y2": d.y2} for d in dets], str(out))
    return FileResponse(out, media_type="image/jpeg")


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
def get_events(video_id: int, response: Response, user: User = Depends(get_current_user),
               db: Session = Depends(get_db),
               limit: int = Query(50, ge=1, le=200),
               offset: int = Query(0, ge=0)):
    _get_video(db, video_id, user)
    q = db.query(Event).filter_by(video_id=video_id).order_by(Event.timestamp_seconds)
    response.headers["X-Total-Count"] = str(q.count())
    evs = q.offset(offset).limit(limit).all()
    return [_event_out(e) for e in evs]


def _event_out(e: Event) -> dict:
    """Event payload, including Phase 6 zone provenance and the
    evidence clip URL (served by the existing /clip endpoint)."""
    out = {"id": e.id, "rule_name": e.rule_name, "title": e.title, "severity": e.severity,
           "timestamp_seconds": e.timestamp_seconds, "verified": e.verified,
           "description": e.description, "zone_name": e.zone_name,
           "track_id": e.track_id, "label": e.label,
           "evidence_frame_id": e.evidence_frame_id, "evidence_clip_url": None}
    if e.evidence_clip_start is not None and e.evidence_clip_end is not None:
        out["evidence_clip_url"] = (
            f"/api/v1/videos/{e.video_id}/clip"
            f"?start={e.evidence_clip_start:.1f}&end={e.evidence_clip_end:.1f}")
    return out


@router.post("/{video_id}/zones", status_code=201)
def create_zone(video_id: int, zone: ZoneIn,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a named region of interest on a video (Phase 6)."""
    _get_video(db, video_id, user)
    row = Zone(video_id=video_id, name=zone.name, x1=zone.x1, y1=zone.y1,
               x2=zone.x2, y2=zone.y2)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "video_id": video_id, "name": row.name,
            "x1": row.x1, "y1": row.y1, "x2": row.x2, "y2": row.y2}


@router.get("/{video_id}/zones")
def list_zones(video_id: int, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    rows = db.query(Zone).filter_by(video_id=video_id).order_by(Zone.id).all()
    return [{"id": z.id, "name": z.name, "x1": z.x1, "y1": z.y1,
             "x2": z.x2, "y2": z.y2} for z in rows]


@router.delete("/{video_id}/zones/{zone_id}")
def delete_zone(video_id: int, zone_id: int,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_video(db, video_id, user)
    row = db.get(Zone, zone_id)
    if not row or row.video_id != video_id:
        raise HTTPException(404, "Zone not found")
    db.delete(row)
    db.commit()
    return {"deleted": zone_id}


@router.post("/{video_id}/events/evaluate-zones")
def evaluate_zone_events(video_id: int, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Run the Phase 6 zone engine over this video's stored zones and
    tracked detections. Returns the events it created."""
    _get_video(db, video_id, user)
    zones = [{"name": z.name, "x1": z.x1, "y1": z.y1, "x2": z.x2, "y2": z.y2}
             for z in db.query(Zone).filter_by(video_id=video_id).all()]
    created = events_svc.evaluate_zones(db, video_id, zones)
    return [_event_out(e) for e in created]


@router.post("/{video_id}/events/{event_id}/verify")
def verify_event_endpoint(video_id: int, event_id: int,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask the VLM to confirm one event from its evidence frame."""
    _get_video(db, video_id, user)
    event = db.get(Event, event_id)
    if not event or event.video_id != video_id:
        raise HTTPException(404, "Event not found")
    verified, message = events_svc.verify_event(db, event)
    return {"id": event.id, "verified": verified, "message": message}


@router.get("/{video_id}/alerts")
def get_alerts(video_id: int, response: Response, user: User = Depends(get_current_user),
               db: Session = Depends(get_db),
               limit: int = Query(50, ge=1, le=200),
               offset: int = Query(0, ge=0)):
    _get_video(db, video_id, user)
    q = db.query(Alert).filter_by(video_id=video_id).order_by(Alert.id.desc())
    response.headers["X-Total-Count"] = str(q.count())
    alerts = q.offset(offset).limit(limit).all()
    return [{"id": a.id, "event_id": a.event_id, "severity": a.severity, "message": a.message,
             "acknowledged": a.acknowledged} for a in alerts]


def _auth_for_sse(request: Request, video_id: int, db: Session) -> User:
    """SSE auth: EventSource cannot send an Authorization header, so
    the token travels in ?token= — either the signed stream token
    (same as the <video> tag) or a plain JWT. Bearer header also
    works (API clients, tests)."""
    token = request.query_params.get("token")
    if token:
        verified = verify_stream_token(token)
        if verified and verified[1] == video_id:
            user = db.get(User, verified[0])
            if user:
                return user
        from ..security import decode_token, is_revoked

        data = decode_token(token)
        if data and not is_revoked(db, data.get("jti")):
            user = db.get(User, int(data["sub"]))
            if user:
                return user
        raise HTTPException(401, "Invalid or expired token")
    return _bearer_user(request, db)


@router.get("/{video_id}/status-stream")
def video_status_stream(video_id: int, request: Request, db: Session = Depends(get_db)):
    """Server-sent events for processing status (Phase 8). Emits
    `data: {"status": ..., "error_message": ...}` every 2 s and
    closes with a final event once the video is ready/failed (or
    after 10 min). The frontend falls back to polling if EventSource
    fails."""
    from fastapi.responses import StreamingResponse

    import json as _json
    import time as _time

    user = _auth_for_sse(request, video_id, db)
    _get_video(db, video_id, user)

    def _gen():
        deadline = _time.time() + 600
        while _time.time() < deadline:
            s = SessionLocal()
            try:
                v = s.get(Video, video_id)
                status = v.status if v else "missing"
                err = v.error_message if v else None
            finally:
                s.close()
            payload = _json.dumps({"status": status, "error_message": err})
            yield f"data: {payload}\n\n"
            if status in ("ready", "failed", "missing"):
                break
            _time.sleep(2)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


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
