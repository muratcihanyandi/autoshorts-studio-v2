"""Publishing schemas (M10, M13 orientation-aware)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PublishResult(BaseModel):
    # Dikey yayinlarda aday dolu; yatay tam kesitlerde NULL + video.
    clip_candidate_id: int | None = None
    source_video_id: int | None = None
    youtube_video_id: str = ""
    visibility: str = "private"
    skipped: bool = False


class ApproveResult(BaseModel):
    clip_candidate_id: int | None = None
    source_video_id: int | None = None
    revision: int


class PublishedVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clip_candidate_id: int | None
    orientation: str = "vertical"
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


class PublishingProfileIn(BaseModel):
    daily_clip_target: int | None = None
    timezone: str | None = None
    publish_times: list[str] | None = None
    auto_approve_metadata: bool | None = None
    paused: bool | None = None


class PublishingProfileOut(BaseModel):
    channel_id: int
    daily_clip_target: int
    timezone: str
    publish_times: list[str] | None
    auto_approve_metadata: bool
    paused: bool
