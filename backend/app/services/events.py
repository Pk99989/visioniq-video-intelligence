"""Configurable event rules with duplicate suppression.

Rule types:
- scene_duration_gt: value = seconds (float); fires when a scene lasts longer.
- caption_keyword: value = substring; fires on scenes whose caption contains it.
- detection_label: value = label; fires on frames with that detection.

An event is NEVER marked verified unless there is a high-confidence
detection (>=0.80) backing it. VLM verification (when a real VLM is
configured) can upgrade an event; the fallback provider cannot.
Duplicate suppression: same video + rule + 30s time bucket fires once.
"""
from sqlalchemy.orm import Session

from ..models import Alert, Caption, Detection, Event, Frame, Scene

SUPPRESSION_WINDOW = 30.0


def _already_fired(db: Session, video_id: int, rule_name: str, ts: float) -> bool:
    bucket = int(ts // SUPPRESSION_WINDOW)
    for e in db.query(Event).filter_by(video_id=video_id, rule_name=rule_name).all():
        if int(e.timestamp_seconds // SUPPRESSION_WINDOW) == bucket:
            return True
    return False


def _emit(db: Session, video_id: int, rule: dict, ts: float, title: str,
          description: str, frame_id=None, verified: bool = False) -> Event | None:
    if _already_fired(db, video_id, rule["name"], ts):
        return None
    event = Event(video_id=video_id, rule_name=rule["name"], severity=rule.get("severity", "info"),
                  title=title, description=description, timestamp_seconds=ts,
                  verified=verified, evidence_frame_id=frame_id)
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
