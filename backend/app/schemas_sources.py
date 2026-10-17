"""Source channel schemas (registration + rights records)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_PERMISSION_VALUES = ("authorized", "rejected")


class SourceCreate(BaseModel):
    youtube_channel_id: str = Field(min_length=3, max_length=64)
    title: str = Field(min_length=1, max_length=160)


class SourceUpdate(BaseModel):
    """Hak kaydı: izin verme/geri çekme ve başlık düzeltmesi."""

    permission_status: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("permission_status")
    @classmethod
    def _valid_transition(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in SOURCE_PERMISSION_VALUES:
            raise ValueError(
                "permission_status 'authorized' veya 'rejected' olmalı"
            )
        return value


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    youtube_channel_id: str
    title: str
    permission_status: str
    authorized_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourcesOut(BaseModel):
    sources: list[SourceOut]
    total: int
    authorized: int


class DiscoverResult(BaseModel):
    sources_checked: int
    new_videos: int
    quota_blocked: bool


class SourceVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_channel_id: int
    youtube_video_id: str
    title: str
    published_at: datetime | None
    duration_seconds: int | None
    status: str
    discovered_at: datetime


class SourceVideosOut(BaseModel):
    videos: list[SourceVideoOut]
    total: int
