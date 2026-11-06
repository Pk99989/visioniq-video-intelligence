"""Configurable event rules with duplicate suppression.

Rule types:
- scene_duration_gt: value = seconds (float); fires when a scene lasts longer.
- caption_keyword: value = substring; fires on scenes whose caption contains it.
- detection_label: value = label; fires on frames with that detection.

An event is NEVER marked verified unless there is a high-confidence
detection (>=0.80) backing it. VLM verification (when a real VLM is
configured) can upgrade an event; the fallback provider cannot.
Duplicate suppression: same video + rule + 30s time bucket fires once.
Zone events (Phase 6) add zone_name/track_id to the suppression key so
two zones or two tracks in the same 30s bucket do not suppress each
other, and carry an evidence clip window served by the existing
GET /videos/{id}/clip endpoint.
"""
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, Caption, Detection, Event, Frame, Scene, Video, Zone

SUPPRESSION_WINDOW = 30.0


def _already_fired(db: Session, video_id: int, rule_name: str, ts: float,
                   zone_name: str | None = None, track_id: int | None = None) -> bool:
    bucket = int(ts // SUPPRESSION_WINDOW)
    q = db.query(Event).filter_by(video_id=video_id, rule_name=rule_name)
    if zone_name is not None:
        q = q.filter_by(zone_name=zone_name)
    if track_id is not None:
        q = q.filter_by(track_id=track_id)
    for e in q.all():
        if int(e.timestamp_seconds // SUPPRESSION_WINDOW) == bucket:
            return True
    return False


def _clip_window(duration: float | None, ts: float) -> tuple[float, float]:
    start = max(0.0, ts - settings.EVENT_CLIP_PRE_SECONDS)
    end = ts + settings.EVENT_CLIP_POST_SECONDS
    if duration:
        end = min(float(duration), end)
    return round(start, 3), round(end, 3)


def _emit(db: Session, video_id: int, rule: dict, ts: float, title: str,
          description: str, frame_id=None, verified: bool = False,
          zone_name: str | None = None, track_id: int | None = None,
          label: str | None = None, clip: tuple[float, float] | None = None) -> Event | None:
    if _already_fired(db, video_id, rule["name"], ts, zone_name, track_id):
        return None
    event = Event(video_id=video_id, rule_name=rule["name"], severity=rule.get("severity", "info"),
                  title=title, description=description, timestamp_seconds=ts,
                  verified=verified, evidence_frame_id=frame_id,
                  zone_name=zone_name, track_id=track_id, label=label,
                  evidence_clip_start=clip[0] if clip else None,
                  evidence_clip_end=clip[1] if clip else None)
    db.add(event)
    db.flush()
    db.add(Alert(event_id=event.id, video_id=video_id, severity=event.severity,
                 message=f"{title} at {ts:.1f}s"))
    return event


def evaluate_rules(db: Session, video_id: int, rules: list[dict]) -> list[Event]:
    created: list[Event] = []
    scenes = db.query(Scene).filter_by(video_id=video_id).all()
    captions = db.query(Caption).filter_by(video_id=video_id).all()
    detections = (db.query(Detection).filter_by(video_id=video_id).all())
    for rule in rules:
        rtype, value, name = rule["rule_type"], str(rule["value"]), rule["name"]
        if rtype == "scene_duration_gt":
            try:
                threshold = float(value)
            except ValueError:
                continue
            for s in scenes:
                if s.end_seconds - s.start_seconds > threshold:
                    ev = _emit(db, video_id, rule, s.start_seconds,
                               f"Long scene: {name}",
                               f"Scene {s.index + 1} lasted {s.end_seconds - s.start_seconds:.1f}s "
                               f"(threshold {threshold}s).")
                    if ev:
                        created.append(ev)
        elif rtype == "caption_keyword":
            for c in captions:
                if value.lower() in c.text.lower():
                    ev = _emit(db, video_id, rule, c.timestamp_seconds,
                               f"Keyword match: {name}",
                               f"Caption at {c.timestamp_seconds:.1f}s contains '{value}'.",
                               frame_id=c.frame_id)
                    if ev:
                        created.append(ev)
        elif rtype == "detection_label":
            for d in detections:
                if d.label.lower() == value.lower():
                    ev = _emit(db, video_id, rule, d.timestamp_seconds,
                               f"Detected {value}: {name}",
                               f"{value} detected at {d.timestamp_seconds:.1f}s "
                               f"(confidence {d.confidence:.2f}).",
                               frame_id=d.frame_id, verified=d.confidence >= 0.80)
                    if ev:
                        created.append(ev)
    db.commit()
    return created


def _frame_size(db: Session, video: Video, frame_id: int, cache: dict) -> tuple[float, float] | None:
    """Frame dimensions for normalising detection coordinates. Frames
    are extracted at full resolution, so the video's stored width /
    height apply; fall back to reading the frame file when they are
    missing (older videos)."""
    if video.width and video.height:
        return float(video.width), float(video.height)
    if frame_id in cache:
        return cache[frame_id]
    frame = db.get(Frame, frame_id)
    size = None
    if frame is not None:
        try:
            import cv2

            img = cv2.imread(frame.file_path)
            if img is not None:
                size = (float(img.shape[1]), float(img.shape[0]))
        except Exception:  # noqa: BLE001 - best effort, caller skips
            size = None
    cache[frame_id] = size
    return size


def _inside(zone, cx: float, cy: float) -> bool:
    x1, y1, x2, y2 = zone["x1"], zone["y1"], zone["x2"], zone["y2"]
    return x1 <= cx <= x2 and y1 <= cy <= y2


def evaluate_zones(db: Session, video_id: int, zones: list[dict]) -> list[Event]:
    """Zone event engine (Phase 6). For every tracked object (Detection
    rows grouped by track_id, in time order) and every zone, watch the
    track centre crossing the zone boundary:

    - zone_enter: centre moves outside -> inside.
    - zone_exit: centre moves inside -> outside.
    - zone_dwell: centre stays inside continuously for
      EVENT_DWELL_SECONDS (one event per stay, at entry + threshold).
    - zone_loitering: centre stays inside continuously for
      EVENT_LOITER_SECONDS — a *candidate* (verified=False, title says
      "possible"), because a long stay alone is not proof of loitering.

    A track that is still inside a zone at its last detection produces
    no exit event — no exit was observed, so none is invented. Each
    event carries zone_name, track_id, label, an evidence frame and an
    evidence clip window [ts - pre, ts + post] clamped to the video.
    """
    created: list[Event] = []
    if not zones:
        return created
    video = db.get(Video, video_id)
    if video is None:
        return created
    detections = (db.query(Detection).filter_by(video_id=video_id)
                  .filter(Detection.track_id.isnot(None))
                  .order_by(Detection.timestamp_seconds).all())
    by_track: dict[int, list[Detection]] = {}
    for d in detections:
        by_track.setdefault(d.track_id, []).append(d)
    size_cache: dict[int, tuple[float, float] | None] = {}
    dwell = settings.EVENT_DWELL_SECONDS
    loiter = settings.EVENT_LOITER_SECONDS
    for track_id, dets in by_track.items():
        label = dets[0].label
        for zone in zones:
            zname = zone["name"]
            inside = False
            entry_ts = entry_frame = None
            dwell_fired = loiter_fired = False
            for d in dets:
                size = _frame_size(db, video, d.frame_id, size_cache)
                if size is None or size[0] <= 0 or size[1] <= 0:
                    continue
                cx = ((d.x1 + d.x2) / 2) / size[0]
                cy = ((d.y1 + d.y2) / 2) / size[1]
                now_in = _inside(zone, cx, cy)
                ts = d.timestamp_seconds
                if now_in and not inside:
                    # Entered the zone.
                    inside, entry_ts, entry_frame = True, ts, d.frame_id
                    dwell_fired = loiter_fired = False
                    ev = _emit(db, video_id, {"name": "zone_enter"}, ts,
                               f"{label} entered {zname}",
                               f"Track {track_id} ({label}) entered zone '{zname}' "
                               f"at {ts:.1f}s.",
                               frame_id=d.frame_id, zone_name=zname,
                               track_id=track_id, label=label,
                               clip=_clip_window(video.duration_seconds, ts))
                    if ev:
                        created.append(ev)
                elif not now_in and inside:
                    # Left the zone.
                    inside = False
                    ev = _emit(db, video_id, {"name": "zone_exit"}, ts,
                               f"{label} left {zname}",
                               f"Track {track_id} ({label}) left zone '{zname}' "
                               f"at {ts:.1f}s after {ts - entry_ts:.1f}s inside.",
                               frame_id=d.frame_id, zone_name=zname,
                               track_id=track_id, label=label,
                               clip=_clip_window(video.duration_seconds, ts))
                    if ev:
                        created.append(ev)
                    entry_ts = entry_frame = None
                elif now_in and inside:
                    held = ts - entry_ts
                    if not dwell_fired and held >= dwell:
                        dwell_fired = True
                        at = entry_ts + dwell
                        ev = _emit(db, video_id, {"name": "zone_dwell"}, at,
                                   f"{label} stayed in {zname} for {dwell:.0f}s",
                                   f"Track {track_id} ({label}) stayed inside zone "
                                   f"'{zname}' for at least {dwell:.1f}s.",
                                   frame_id=d.frame_id, zone_name=zname,
                                   track_id=track_id, label=label,
                                   clip=_clip_window(video.duration_seconds, at))
                        if ev:
                            created.append(ev)
                    if not loiter_fired and held >= loiter:
                        loiter_fired = True
                        at = entry_ts + loiter
                        ev = _emit(db, video_id, {"name": "zone_loitering",
                                                  "severity": "warning"}, at,
                                   f"Possible loitering in {zname}",
                                   f"Track {track_id} ({label}) stayed inside zone "
                                   f"'{zname}' for at least {loiter:.1f}s. "
                                   f"Candidate only — needs VLM verification.",
                                   frame_id=d.frame_id, zone_name=zname,
                                   track_id=track_id, label=label,
                                   clip=_clip_window(video.duration_seconds, at))
                        if ev:
                            created.append(ev)
    db.commit()
    return created


def verify_event(db: Session, event: Event) -> tuple[bool, str]:
    """VLM verification for one event (Phase 6). Asks the VLM whether
    the event's object is visible in its evidence frame. Only
    presence-type events (zone_enter / zone_dwell / zone_loitering)
    are verifiable this way — for a zone_exit the claim is an absence,
    which a single frame cannot confirm, so it is reported as such.
    Returns (verified, message). A False answer or an unparseable one
    leaves verified=False; the event is never silently upgraded."""
    from . import vlm as vlm_svc

    if event.rule_name == "zone_exit":
        return False, ("Exit events are not VLM-verified: a single frame "
                       "cannot confirm an absence.")
    if event.rule_name not in ("zone_enter", "zone_dwell", "zone_loitering"):
        return False, f"Rule {event.rule_name!r} has no VLM verification."
    if not event.evidence_frame_id:
        return False, "No evidence frame on this event."
    frame = db.get(Frame, event.evidence_frame_id)
    if frame is None:
        return False, "Evidence frame not found."
    if settings.VLM_PROVIDER == "fallback" or not settings.VLM_BASE_URL:
        return False, ("No VLM configured (VLM_PROVIDER=fallback) — "
                       "event stays unverified.")
    label = event.label or "object"
    zone = f" in zone '{event.zone_name}'" if event.zone_name else ""
    answer = vlm_svc.ask_yes_no(
        frame.file_path, f"Is there a {label} visible in this image{zone}?")
    if answer is True:
        event.verified = True
        db.commit()
        return True, f"VLM confirmed a {label} is visible{zone}."
    if answer is False:
        event.description += " [VLM did not confirm this event.]"
        db.commit()
        return False, f"VLM did not confirm a {label} is visible{zone}."
    return False, "VLM gave no clear answer — event stays unverified."
