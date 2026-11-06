"""Pydantic request/response contracts. The API never trusts raw client
JSON beyond these models."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordResetRequestIn(BaseModel):
    email: str


class PasswordResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VideoOut(BaseModel):
    id: int
    title: str
    original_filename: str
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    status: str
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    video_id: Optional[int] = None
    top_k: int = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # Phase 4 filters (all optional, all owner-scoped server-side):
    label: Optional[str] = None          # only frames detecting this label
    provider: Optional[str] = None       # only captions from this provider
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    rerank: Optional[bool] = None        # None = follow RERANKER_MODEL


class SearchHit(BaseModel):
    video_id: int
    frame_id: int
    timestamp_seconds: float
    score: float
    caption: str
    frame_path: Optional[str] = None
    detections: List[str] = []
    provider: Optional[str] = None


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    video_id: Optional[int] = None
    conversation_id: Optional[int] = None


class EventRuleIn(BaseModel):
    name: str
    rule_type: str  # scene_duration_gt | caption_keyword | detection_label
    value: str
    severity: str = "info"


class ZoneIn(BaseModel):
    """A rectangular region of interest, normalised 0..1 (Phase 6)."""
    name: str
    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def _check_box(self):
        for f in ("x1", "y1", "x2", "y2"):
            v = getattr(self, f)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{f} must be between 0 and 1")
        if not (self.x1 < self.x2 and self.y1 < self.y2):
            raise ValueError("need x1 < x2 and y1 < y2")
        return self


class ReportIn(BaseModel):
    video_id: int
    kind: str = "summary"  # summary | incident | timeline
    format: str = "json"  # json | pdf
