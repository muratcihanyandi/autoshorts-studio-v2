"""Source channel schemas (registration + rights records)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_PERMISSION_VALUES = ("authorized", "rejected")
RULE_KEYS = {"exclude_title_patterns", "max_age_days"}


def _validate_rules(value: dict | None) -> dict | None:
    if value is None:
        return value
    unknown = set(value) - RULE_KEYS
    if unknown:
        raise ValueError(f"bilinmeyen kural anahtarları: {sorted(unknown)}")
    patterns = value.get("exclude_title_patterns")
    if patterns is not None:
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) for p in patterns
        ):
            raise ValueError("exclude_title_patterns metin listesi olmalı")
    max_age = value.get("max_age_days")
    if max_age is not None and (not isinstance(max_age, int) or max_age < 1):
        raise ValueError("max_age_days pozitif tam sayı olmalı")
    return value


class SourceCreate(BaseModel):
    """Kaynak kaydı. youtube_channel_id her platformun kanal anahtarını
    taşır (youtube: UC kimliği; twitch/kick: kanal adresi)."""

    youtube_channel_id: str = Field(min_length=3, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    platform: Literal["youtube", "twitch", "kick"] = "youtube"
    character_id: int | None = None
    reaction_source: bool = False
    trim_start_seconds: float = Field(default=0.0, ge=0)
    trim_end_seconds: float = Field(default=0.0, ge=0)
    filter_rules: dict | None = None

    @field_validator("filter_rules")
    @classmethod
    def _rules_valid(cls, value: dict | None) -> dict | None:
        return _validate_rules(value)


class SourceUpdate(BaseModel):
    """Hak kaydı: izin verme/geri çekme ve başlık düzeltmesi.

    M13 alanları (platform, character_id, reaction_source, trim) de
    PATCH ile güncellenir; character_id=null bağı çözer."""

    permission_status: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    platform: Literal["youtube", "twitch", "kick"] | None = None
    character_id: int | None = None
    reaction_source: bool | None = None
    trim_start_seconds: float | None = Field(default=None, ge=0)
    trim_end_seconds: float | None = Field(default=None, ge=0)
    filter_rules: dict | None = None

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

    @field_validator("filter_rules")
    @classmethod
    def _rules_valid(cls, value: dict | None) -> dict | None:
        return _validate_rules(value)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    youtube_channel_id: str
    title: str
    platform: str
    character_id: int | None
    # Görünüm kolaylığı için karakter adı (rota katmanı doldurur).
    character_name: str | None = None
    reaction_source: bool
    trim_start_seconds: float
    trim_end_seconds: float
    permission_status: str
    authorized_at: datetime | None
    filter_rules: dict
    created_at: datetime
    updated_at: datetime


class SourcesOut(BaseModel):
    sources: list[SourceOut]
    total: int
    authorized: int


class DiscoverResult(BaseModel):
    sources_checked: int
    new_videos: int
    new_excluded: int
    quota_blocked: bool
    # YouTube dışı platformlar keşifte atlanır (manuel VOD içe aktarılır).
    skipped_platforms: list[str] = Field(default_factory=list)


class ManualVideoCreate(BaseModel):
    """Manuel VOD içe aktarımı (twitch/kick): URL + başlık."""

    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)


class PlanningResult(BaseModel):
    planned: int
    skipped: int


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


class WebcamRegion(BaseModel):
    x: int
    y: int
    w: int
    h: int


class WebcamCalibrationIn(BaseModel):
    region: WebcamRegion
    manual: bool = True
    min_confidence: float | None = None


class WebcamCalibrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_channel_id: int
    region_x: int
    region_y: int
    region_w: int
    region_h: int
    manual: bool
    min_confidence: float | None
    updated_at: datetime
