"""Publishing schemas (M10)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PublishResult(BaseModel):
    clip_candidate_id: int
    youtube_video_id: str = ""
    visibility: str = "private"
    skipped: bool = False


class ApproveResult(BaseModel):
    clip_candidate_id: int
    revision: int


class PublishedVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clip_candidate_id: int
    channel_id: int
    youtube_video_id: str
    visibility: str
    status: str
    title: str
    published_at: datetime | None
    last_error: str | None
    created_at: datetime


class PublishedVideosOut(BaseModel):
    videos: list[PublishedVideoOut]
    total: int
