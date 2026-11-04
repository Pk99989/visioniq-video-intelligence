"""Hierarchical summarization, built only from stored captions.

Scene captions -> scene summaries -> chronological video summary.
Length is configurable: short keeps 1 line per scene, medium 2, long
keeps the full scene caption. Nothing is invented beyond the captions;
if a video has no captions, the summary says so."""
from sqlalchemy.orm import Session

from ..models import Caption, Scene


def scene_summaries(db: Session, video_id: int) -> list[dict]:
    scenes = db.query(Scene).filter_by(video_id=video_id).order_by(Scene.index).all()
    out = []
    for s in scenes:
        caps = (db.query(Caption).filter_by(scene_id=s.id)
                .order_by(Caption.timestamp_seconds).all())
        text = " ".join(c.text for c in caps) if caps else "(no caption for this scene)"
        out.append({"scene_index": s.index, "start_seconds": s.start_seconds,
                    "end_seconds": s.end_seconds, "text": text})
    return out


def summarize_video(db: Session, video_id: int, length: str = "medium") -> dict:
    scenes = scene_summaries(db, video_id)
    if not scenes:
        return {"video_id": video_id, "length": length, "summary": "No scenes were extracted for this video.",
                "timeline": [], "scene_count": 0}
    per_scene = {"short": 1, "medium": 2, "long": 99}.get(length, 2)
    lines = []
    for s in scenes:
        # keep the first `per_scene` sentences of the scene text
        sentences = [x.strip() for x in s["text"].split(". ") if x.strip()]
        keep = ". ".join(sentences[:per_scene])
        if keep and not keep.endswith("."):
            keep += "."
        lines.append(f"[{s['start_seconds']:.1f}s–{s['end_seconds']:.1f}s] {keep}")
    return {"video_id": video_id, "length": length,
            "summary": " ".join(lines), "timeline": scenes, "scene_count": len(scenes)}
