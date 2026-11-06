"""Structured data model. Every vector/frame/caption keeps video_id,
scene_id, timestamp_seconds and frame_path so an answer can always be
traced back to a concrete moment in a concrete video."""
import json
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="user", nullable=False)  # user | admin
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    videos = relationship("Video", back_populates="owner", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    thumbnail_path = Column(String(1000), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=False, default=0)
    status = Column(String(32), default="uploaded", nullable=False, index=True)
    # uploaded | processing | ready | failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    owner = relationship("User", back_populates="videos")
    scenes = relationship("Scene", back_populates="video", cascade="all, delete-orphan")
    frames = relationship("Frame", back_populates="video", cascade="all, delete-orphan")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    status = Column(String(32), default="queued", nullable=False)
    # queued | running | done | failed
    attempts = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Scene(Base):
    __tablename__ = "scenes"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    index = Column(Integer, nullable=False)
    start_seconds = Column(Float, nullable=False)
    end_seconds = Column(Float, nullable=False)
    video = relationship("Video", back_populates="scenes")
    frames = relationship("Frame", back_populates="scene")
    captions = relationship("Caption", back_populates="scene", cascade="all, delete-orphan")


class Frame(Base):
    __tablename__ = "frames"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=True)
    timestamp_seconds = Column(Float, nullable=False)
    file_path = Column(String(1000), nullable=False)
    embedding_json = Column(Text, nullable=True)  # JSON list[float], length EMBEDDING_DIM
    video = relationship("Video", back_populates="frames")
    scene = relationship("Scene", back_populates="frames")
    captions = relationship("Caption", back_populates="frame", cascade="all, delete-orphan")
    detections = relationship("Detection", back_populates="frame", cascade="all, delete-orphan")

    def embedding(self):
        return json.loads(self.embedding_json) if self.embedding_json else None


class Caption(Base):
    __tablename__ = "captions"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id"), nullable=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=True)
    timestamp_seconds = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    provider = Column(String(64), nullable=False, default="fallback")
    model = Column(String(255), nullable=True)
    scene = relationship("Scene", back_populates="captions")
    frame = relationship("Frame", back_populates="captions")


class Detection(Base):
    __tablename__ = "detections"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id"), nullable=False, index=True)
    track_id = Column(Integer, nullable=True)
    label = Column(String(128), nullable=False)
    confidence = Column(Float, nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)
    x2 = Column(Float, nullable=False)
    y2 = Column(Float, nullable=False)
    timestamp_seconds = Column(Float, nullable=False)
    frame = relationship("Frame", back_populates="detections")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    rule_name = Column(String(255), nullable=False)
    severity = Column(String(32), default="info", nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    timestamp_seconds = Column(Float, nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    evidence_frame_id = Column(Integer, ForeignKey("frames.id"), nullable=True)
    # Phase 6: zone provenance + evidence clip window (served by the
    # existing GET /videos/{id}/clip?start=&end= endpoint).
    zone_name = Column(String(255), nullable=True)
    track_id = Column(Integer, nullable=True)
    label = Column(String(128), nullable=True)
    evidence_clip_start = Column(Float, nullable=True)
    evidence_clip_end = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Zone(Base):
    """A named rectangular region of interest on a video (Phase 6).

    Coordinates are normalised 0..1 relative to the video frame
    (x1 < x2, y1 < y2). Zones belong to one video and are owner-scoped
    through it; the event engine watches track centres crossing them.
    """
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)
    x2 = Column(Float, nullable=False)
    y2 = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    severity = Column(String(32), default="info", nullable=False)
    message = Column(Text, nullable=False)
    acknowledged = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)
    title = Column(String(500), default="Chat", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    conversation = relationship("Conversation", back_populates="messages")


class RevokedToken(Base):
    """JWT revocation list (Phase 3). A token is identified by its jti;
    logout inserts its jti here, and get_current_user rejects it."""
    __tablename__ = "revoked_tokens"
    id = Column(Integer, primary_key=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PasswordResetToken(Base):
    """Single-use password-reset token, stored as a SHA-256 hash (never
    the raw token). Expires after 1 hour; marked used on success."""
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(64), nullable=False)  # summary | incident | timeline
    file_path = Column(String(1000), nullable=False)
    format = Column(String(16), default="json", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
