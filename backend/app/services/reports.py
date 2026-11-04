"""Reports: JSON always; PDF via reportlab when available. Every report
carries the video id, timeline, events and timestamp citations so it can
be checked against the source video."""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Event, Video
from .summarization import summarize_video


def build_report_data(db: Session, video: Video, kind: str) -> dict:
    summary = summarize_video(db, video.id, length="medium")
    events = (db.query(Event).filter_by(video_id=video.id)
              .order_by(Event.timestamp_seconds).all())
    return {
        "video_id": video.id, "title": video.title, "kind": kind,
        "duration_seconds": video.duration_seconds,
        "summary": summary["summary"], "timeline": summary["timeline"],
        "events": [{"timestamp_seconds": e.timestamp_seconds, "title": e.title,
                    "severity": e.severity, "verified": e.verified,
                    "description": e.description} for e in events],
        "evidence_note": "Timestamps refer to the original video file; frame images are stored under storage/.",
    }


def write_json_report(data: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def write_pdf_report(data: dict, out_path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = [Paragraph(f"VisionIQ Report — {data['title']}", styles["Title"]),
             Spacer(1, 6 * mm),
             Paragraph(f"Video ID: {data['video_id']} | Kind: {data['kind']}", styles["Normal"]),
             Spacer(1, 4 * mm),
             Paragraph("Summary", styles["Heading2"]),
             Paragraph(data["summary"] or "(no summary)", styles["Normal"]),
             Spacer(1, 4 * mm),
             Paragraph("Event timeline", styles["Heading2"])]
    for ev in data["events"]:
        story.append(Paragraph(
            f"{ev['timestamp_seconds']:.1f}s — {ev['title']} [{ev['severity']}] "
            f"verified={ev['verified']}", styles["Normal"]))
    if not data["events"]:
        story.append(Paragraph("(no events)", styles["Normal"]))
    SimpleDocTemplate(str(out_path), pagesize=A4).build(story)
    return out_path
