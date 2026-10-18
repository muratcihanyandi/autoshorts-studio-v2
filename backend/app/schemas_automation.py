"""Channel automation API schemas (Start/Stop era).

The channel settings modal, engine-state rows, and the per-channel
horizontal/shorts listings all live here. Tags come from the central
StatusService — the API only transports them.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AutomationActionOut(BaseModel):
    channel_id: int
    automation_state: str
    cancelled_jobs: int | None = None
    refill: dict | None = None


class EngineStateOut(BaseModel):
    channel_id: int
    name: str
    handle: str | None = None
    status: str
    ribbon_color: str
    automation_state: str
    engine_activity: str
    horizontal_stock: int
    horizontal_stock_target: int
    queued_horizontal: int
    shorts_ready: int
    full_cuts_ready: int
    last_error: str | None = None
    last_error_at: str | None = None
    last_success_at: str | None = None


class ChannelSettingsIn(BaseModel):
    """PUT /channels/{id}/automation — settings only; state changes go
    through the start/stop/pause actions."""

    horizontal_stock_target: int | None = Field(default=None, ge=1, le=50)
    # Gunluk yayin limitleri (0 = sinirsiz): dikey shortlar ve yatay
    # tam kesitler ayri sayilir.
    daily_vertical_limit: int | None = Field(default=None, ge=0, le=50)
    daily_horizontal_limit: int | None = Field(default=None, ge=0, le=50)
    title_mode: str | None = None
    description_mode: str | None = None
    tags_mode: str | None = None
    content_warning_mode: str | None = None
    ai_disclosure_mode: str | None = None
    channel_system_prompt: str | None = None
    character_ids: list[int] | None = None


class FollowedCharacterOut(BaseModel):
    character_id: int
    name: str
    source_count: int
    followed_at: str | None = None


class ChannelSettingsOut(BaseModel):
    channel_id: int
    automation_state: str
    horizontal_stock_target: int
    daily_vertical_limit: int
    daily_horizontal_limit: int
    title_mode: str
    description_mode: str
    tags_mode: str
    content_warning_mode: str
    ai_disclosure_mode: str
    channel_system_prompt: str | None = None
    characters: list[FollowedCharacterOut] = Field(default_factory=list)


class ChannelVideoOut(BaseModel):
    source_video_id: int
    title: str
    tag: str
    status: str
    platform: str | None = None
    duration_seconds: float | None = None
    file_bytes: int | None = None
    file_path: str | None = None
    error: str | None = None


class ChannelVideosOut(BaseModel):
    videos: list[ChannelVideoOut]
    total: int


class ChannelShortOut(BaseModel):
    rendered_clip_id: int
    tag: str
    status: str
    orientation: str
    clip_candidate_id: int | None = None
    source_video_id: int | None = None
    duration_seconds: float
    file_bytes: int
    width: int
    height: int
    error: str | None = None


class ChannelShortsOut(BaseModel):
    shorts: list[ChannelShortOut]
    total: int


class WorkerHealthOut(BaseModel):
    enabled: bool
    running: bool
    worker_id: str | None = None
    started_at: str | None = None
    last_tick_at: str | None = None
    jobs_processed: int = 0
