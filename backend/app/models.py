"""SQLAlchemy domain models (Milestone 3: channels and friends).

Timestamps are timezone-aware and server-defaulted. JSONB is used on
PostgreSQL; the sqlite variant keeps the same models testable in-memory.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON as JSONVariant
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on PostgreSQL, plain JSON under sqlite (tests).
JSONColumn = JSONB().with_variant(JSONVariant(), "sqlite")

# BigInteger PK: sqlite only autoincrements plain INTEGER primary keys.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class ChannelStatus(str, enum.Enum):
    pending = "pending"
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


SOURCE_PERMISSION_STATUSES = ("pending", "authorized", "rejected")

SOURCE_VIDEO_STATUSES = ("discovered", "excluded", "planned", "processed")

MEDIA_ASSET_STATUSES = (
    "downloading",
    "downloaded",
    "inspected",
    "transcribed",
    "analyzed",
    "processed",
    "failed",
)

MEDIA_ASSET_STAGES = ("download", "inspect", "transcript", "analysis", "candidates")

CLIP_CANDIDATE_STATUSES = ("candidate", "rejected", "selected")

RENDERED_CLIP_STATUSES = ("rendering", "rendered", "review", "failed")


class Channel(Base):
    """A YouTube publishing channel the studio manages."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str | None] = mapped_column(Text)
    youtube_channel_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[ChannelStatus] = mapped_column(
        SAEnum(
            ChannelStatus,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="ck_channels_status",
        ),
        default=ChannelStatus.pending,
        nullable=False,
    )
    ribbon_color: Mapped[str] = mapped_column(Text, nullable=False, default="#3550c4")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthCredential(Base):
    """Encrypted OAuth tokens for a channel (one credential set per channel)."""

    __tablename__ = "oauth_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="youtube")
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(Text)
    obtained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OAuthState(Base):
    """Single-use, expiring CSRF state for the OAuth handshake."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceChannel(Base):
    """An authorized source channel feeding one publishing channel."""

    __tablename__ = "source_channels"
    __table_args__ = (
        UniqueConstraint("channel_id", "youtube_channel_id", name="uq_source_per_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    youtube_channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    permission_status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "permission_status IN ('pending', 'authorized', 'rejected')",
            name="ck_source_channels_permission",
        ),
        default="pending",
        nullable=False,
    )
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filter_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONColumn, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PublishingProfile(Base):
    """Channel-specific publishing settings."""

    __tablename__ = "publishing_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    daily_clip_target: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Istanbul")
    publish_window_start: Mapped[str | None] = mapped_column(Text)
    publish_window_end: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONColumn, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AuditEvent(Base):
    """Append-only operational trail; channel_id survives channel deletion."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceVideo(Base):
    """A video discovered under an authorized source channel.

    The unique (source_channel_id, youtube_video_id) pair is the
    duplicate guard: repeated discovery never creates a second record.
    """

    __tablename__ = "source_videos"
    __table_args__ = (
        UniqueConstraint(
            "source_channel_id", "youtube_video_id", name="uq_source_video_per_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_channel_id: Mapped[int] = mapped_column(
        ForeignKey("source_channels.id", ondelete="CASCADE"), nullable=False
    )
    youtube_video_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('discovered', 'excluded', 'planned', 'processed')",
            name="ck_source_videos_status",
        ),
        default="discovered",
        nullable=False,
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class QuotaUsage(Base):
    """Daily YouTube Data API quota units spent (1 row per day)."""

    __tablename__ = "quota_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    units_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlanningDecision(Base):
    """Durable planning ledger: exactly one decision per source video.

    'planned' videos are eligible for job creation (Milestone 6);
    'skipped' carries the reason. The unique source_video_id makes
    repeated planning runs idempotent.
    """

    __tablename__ = "planning_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_video_id: Mapped[int] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "decision IN ('planned', 'skipped')",
            name="ck_planning_decisions_decision",
        ),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppMeta(Base):
    """Runtime key/value state (migration 0001): schema markers, and the
    site-managed runtime settings override blob stored under
    'runtime_settings'."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LlmProvider(Base):
    """One LLM endpoint in the bounded-fallback chain (ADR-011).

    At most three rows exist; enabled rows are tried in priority order.
    api_key_enc is Fernet-encrypted and never leaves the service layer.
    """

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    provider_type: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "provider_type IN ('openai', 'anthropic', 'google')",
            name="ck_llm_providers_type",
        ),
        nullable=False,
    )
    api_base: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LlmRequestLog(Base):
    """One provider attempt: status category + latency, grouped by the
    originating request's UUID. Never stores prompts or keys."""

    __tablename__ = "llm_request_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    provider_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Job(Base):
    """Durable job row (ADR-006: PostgreSQL is the only durable store).

    States: queued -> running -> succeeded | failed | cancelled.
    'cancelling' marks a running job the worker should not retry; the
    worker settles it as cancelled. heartbeat_at + attempts drive stale
    recovery after crashes/restarts.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('queued', 'running', 'cancelling', 'succeeded', "
            "'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        nullable=False,
        default="queued",
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MediaAsset(Base):
    """One downloaded source video and its pipeline progress (M7).

    Unique source_video_id makes the pipeline idempotent: a retried job
    resumes at 'stage' instead of redownloading. 'status' is the coarse
    row state; 'stage' is the next pending pipeline stage.
    """

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_video_id: Mapped[int] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    origin: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "origin IN ('youtube', 'local_import')", name="ck_media_assets_origin"
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('downloading', 'downloaded', 'inspected', 'transcribed', "
            "'analyzed', 'processed', 'failed')",
            name="ck_media_assets_status",
        ),
        default="downloading",
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "stage IN ('download', 'inspect', 'transcript', 'analysis', 'candidates')",
            name="ck_media_assets_stage",
        ),
        default="download",
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MediaInspection(Base):
    """ffprobe metadata for one media asset (M7)."""

    __tablename__ = "media_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    duration_seconds: Mapped[float] = mapped_column(
        CheckConstraint("duration_seconds > 0", name="ck_media_inspections_duration"),
        nullable=False,
    )
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[float] = mapped_column(nullable=False)
    video_codec: Mapped[str] = mapped_column(Text, nullable=False)
    audio_codec: Mapped[str | None] = mapped_column(Text)
    has_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    format_name: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Transcript(Base):
    """Timestamped caption segments for one media asset (M7).

    'source' records how the transcript was obtained; raw_path keeps the
    sidecar file so the original transcript stays recoverable (M9).
    """

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(Text, nullable=False, default="tr")
    source: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "source IN ('sidecar', 'auto_caption')", name="ck_transcripts_source"
        ),
        nullable=False,
    )
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONColumn, nullable=False, default=list
    )
    raw_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClipCandidate(Base):
    """A scored vertical-clip window cut from a source video (M7).

    Timestamps always satisfy 0 <= start < end <= source duration.
    Near-duplicates are kept with status='rejected' and a pointer to the
    candidate they duplicate, so decisions stay auditable.
    """

    __tablename__ = "clip_candidates"
    __table_args__ = (
        CheckConstraint("end_seconds > start_seconds", name="ck_clip_candidates_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_video_id: Mapped[int] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_seconds: Mapped[float] = mapped_column(nullable=False)
    end_seconds: Mapped[float] = mapped_column(nullable=False)
    duration_seconds: Mapped[float] = mapped_column(nullable=False)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('candidate', 'rejected', 'selected')",
            name="ck_clip_candidates_status",
        ),
        default="candidate",
        nullable=False,
    )
    duplicate_of_candidate_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebcamCalibration(Base):
    """Streamer-specific webcam calibration (M8).

    A manual region wins over detection outright; min_confidence
    overrides the default review threshold for this source only.
    """

    __tablename__ = "webcam_calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_channel_id: Mapped[int] = mapped_column(
        ForeignKey("source_channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    region_x: Mapped[int] = mapped_column(Integer, nullable=False)
    region_y: Mapped[int] = mapped_column(Integer, nullable=False)
    region_w: Mapped[int] = mapped_column(Integer, nullable=False)
    region_h: Mapped[int] = mapped_column(Integer, nullable=False)
    manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_confidence: Mapped[float | None] = mapped_column(
        CheckConstraint(
            "min_confidence IS NULL OR (min_confidence >= 0 AND min_confidence <= 1)",
            name="ck_webcam_calibrations_confidence",
        )
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RenderedClip(Base):
    """One rendered 9:16 clip from a clip candidate (M8).

    'review' means webcam detection was uncertain — nothing rendered;
    the operator can calibrate the source and re-run. Unique
    clip_candidate_id keeps re-runs idempotent.
    """

    __tablename__ = "rendered_clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("clip_candidates.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('rendering', 'rendered', 'review', 'failed')",
            name="ck_rendered_clips_status",
        ),
        default="rendering",
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    webcam_region: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn)
    webcam_confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
