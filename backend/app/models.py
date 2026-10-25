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

# Kaynağin çıktı yönü (Görev 2): 'auto' mevcut reaction_source bayrağına
# göre karar verir, 'vertical' yalnız dikey short üretir (yatay dosya
# üretim sonrası silinir), 'horizontal' budanmış yatay tam kesit üretir.
OUTPUT_ORIENTATIONS = ("auto", "vertical", "horizontal")

SOURCE_VIDEO_STATUSES = (
    "discovered",
    "excluded",
    "planned",
    "processed",
    "confirmed",
)

# Kanal otomasyon durum makinesi (Baslat/Durdur): 'stopped' tum isleri
# durdurur, 'running' tam otomasyon, 'paused' yayinlamayi bekletir
# (uretim surer), 'error' kalici is hatasi sonrasi mudahale bekler.
AUTOMATION_STATES = ("stopped", "running", "paused", "error")

# Kanal ayarlarindaki uc durumlu secimler: 'auto' = LLM karar verir,
# 'on' = dogrudan acik, 'off' = dogrudan kapali.
SETTING_MODES = ("auto", "on", "off")

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

CLIP_METADATA_STATUSES = ("draft", "approved", "rejected")


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"


class UserPlan(str, enum.Enum):
    free = "free"
    pro = "pro"


class User(Base):
    """A studio account (account isolation, madde 6).

    The first account — migrated from the single-operator ``studio_auth``
    era — is an admin. Later accounts may be operators whose plan gates
    some features (see auth_service plan limits)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="ck_users_role",
        ),
        default=UserRole.admin,
        nullable=False,
    )
    plan: Mapped[UserPlan] = mapped_column(
        SAEnum(
            UserPlan,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="ck_users_plan",
        ),
        default=UserPlan.pro,
        nullable=False,
    )
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


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
    # Hesap izolasyonu: kanalı oluşturan hesap. NULL = migration öncesi
    # kalıntı (yalnız admin görür); silinen hesapta kanal yerinde kalır.
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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


class Character(Base):
    """A streamer/person tracked by the studio (M13).

    Binds N source channels across platforms; the reference face (from
    the uploaded photo) validates webcam regions, and the optional
    system_prompt overrides the global metadata prompt for this
    character's clips.
    """

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # MEDIA_ROOT altinda goreli yol, orn. characters/7_ab12cd3f.jpg
    photo_path: Mapped[str | None] = mapped_column(String(255))
    # Kirpilmis referans yuz (characters/7_ref.png); yuz yoksa None.
    reference_face_path: Mapped[str | None] = mapped_column(String(255))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceChannel(Base):
    """An authorized source channel feeding one publishing channel.

    youtube_channel_id carries the platform channel key for every
    platform: a UC... id for YouTube, the channel URL/name for
    Twitch/Kick (discovery itself is YouTube-only in M13; other
    platforms import VODs manually).
    """

    __tablename__ = "source_channels"
    __table_args__ = (
        UniqueConstraint("channel_id", "youtube_channel_id", name="uq_source_per_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[int | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "platform IN ('youtube', 'twitch', 'kick')",
            name="ck_source_channels_platform",
        ),
        default="youtube",
        nullable=False,
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
    # Reaksiyon kaynagi: budanmis yatay tam kesit + dikey shortlar uretilir.
    reaction_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Çıktı yönü (Görev 2): auto/vertical/horizontal; auto reaction_source
    # bayrağına düşer, vertical yatay tam kesiti hiç üretmez, horizontal
    # bayraktan bağımsız yatay tam kesit üretir.
    output_orientation: Mapped[str] = mapped_column(
        String(12),
        CheckConstraint(
            "output_orientation IN ('auto', 'vertical', 'horizontal')",
            name="ck_source_channels_output_orientation",
        ),
        server_default="auto",
        nullable=False,
    )
    trim_start_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    trim_end_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
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
    """Channel-specific publishing and automation settings.

    automation_state is the engine's persistent Start/Stop state
    (stopped/running/paused/error); horizontal_stock_target drives the
    stock-aware download feed (default 3); the *_mode fields are the
    auto/on/off choices for metadata generation and content
    notifications; channel_system_prompt feeds this channel's LLM calls
    before the character/global prompts.
    """

    __tablename__ = "publishing_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    daily_clip_target: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Gunluk yatay (tam kesit) yayin limiti; dikeyde daily_clip_target.
    daily_horizontal_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Istanbul")
    publish_window_start: Mapped[str | None] = mapped_column(Text)
    publish_window_end: Mapped[str | None] = mapped_column(Text)
    automation_state: Mapped[str] = mapped_column(
        String(12),
        CheckConstraint(
            "automation_state IN ('stopped', 'running', 'paused', 'error')",
            name="ck_publishing_profiles_automation_state",
        ),
        default="stopped",
        nullable=False,
    )
    horizontal_stock_target: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    title_mode: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint(
            "title_mode IN ('auto', 'on', 'off')",
            name="ck_publishing_profiles_title_mode",
        ),
        default="auto",
        nullable=False,
    )
    description_mode: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint(
            "description_mode IN ('auto', 'on', 'off')",
            name="ck_publishing_profiles_description_mode",
        ),
        default="auto",
        nullable=False,
    )
    tags_mode: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint(
            "tags_mode IN ('auto', 'on', 'off')",
            name="ck_publishing_profiles_tags_mode",
        ),
        default="auto",
        nullable=False,
    )
    content_warning_mode: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint(
            "content_warning_mode IN ('auto', 'on', 'off')",
            name="ck_publishing_profiles_content_warning_mode",
        ),
        default="auto",
        nullable=False,
    )
    ai_disclosure_mode: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint(
            "ai_disclosure_mode IN ('auto', 'on', 'off')",
            name="ck_publishing_profiles_ai_disclosure_mode",
        ),
        default="auto",
        nullable=False,
    )
    channel_system_prompt: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONColumn, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChannelCharacter(Base):
    """Which characters a publishing channel follows (channel settings
    modal). Stock refill only processes sources bound to followed
    characters; the unique pair prevents duplicate follows."""

    __tablename__ = "channel_characters"
    __table_args__ = (
        UniqueConstraint("channel_id", "character_id", name="uq_channel_character"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
            "status IN ('discovered', 'excluded', 'planned', 'processed', "
            "'confirmed')",
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
    # Yeniden deneme bekleme araligi: run_at gelmeden is alınmaz.
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
            "source IN ('sidecar', 'auto_caption', 'whisper')",
            name="ck_transcripts_source",
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
    """One rendered clip from a clip candidate (M8), or the trimmed
    horizontal full cut of a reaction source's video (M13).

    'review' means webcam detection was uncertain — nothing rendered;
    the operator can calibrate the source and re-run. The
    (clip_candidate_id, orientation) pair keeps re-runs idempotent;
    horizontal full cuts carry a NULL candidate and reference the
    source video instead.
    """

    __tablename__ = "rendered_clips"
    __table_args__ = (
        UniqueConstraint(
            "clip_candidate_id", "orientation", name="uq_rendered_clip_candidate_orientation"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("clip_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        nullable=True,
    )
    orientation: Mapped[str] = mapped_column(
        String(12),
        CheckConstraint(
            "orientation IN ('vertical', 'horizontal')",
            name="ck_rendered_clips_orientation",
        ),
        default="vertical",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('rendering', 'rendered', 'review', 'failed',"
            " 'removed')",
            name="ck_rendered_clips_status",
        ),
        default="rendering",
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Onizleme/thumbnail jpg (metadata onaylandiginda uretilir), goreli yol.
    thumbnail_path: Mapped[str | None] = mapped_column(String(255))
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


class CorrectedTranscript(Base):
    """LLM-corrected Turkish transcript, parallel to the original (M9).

    The original transcripts row is never modified — timestamps are
    copied verbatim from it, only the text is corrected; segments the
    provider marked uncertain carry uncertain=True.
    """

    __tablename__ = "corrected_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONColumn, nullable=False, default=list
    )
    corrected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MetadataTemplate(Base):
    """Channel-specific metadata template (M9).

    Patterns may reference {title}, {summary}, {channel}; unknown
    placeholders are left intact. Template changes affect only this
    channel.
    """

    __tablename__ = "metadata_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    title_pattern: Mapped[str] = mapped_column(Text, nullable=False, default="{title}")
    description_pattern: Mapped[str] = mapped_column(
        Text, nullable=False, default="{summary}"
    )
    base_tags: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ClipMetadata(Base):
    """One metadata revision for a clip candidate (M9), or for the
    horizontal full cut of a reaction source's video (M13 — candidate
    NULL, source_video set).

    Revisions are append-only: regenerating inserts revision max+1 and
    earlier rows stay for audit. Lengths follow YouTube limits
    (title <= 100, description <= 5000).
    """

    __tablename__ = "clip_metadata"
    __table_args__ = (
        UniqueConstraint("clip_candidate_id", "revision", name="uq_clip_metadata_rev"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("clip_candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False, default=list)
    # M13: viral kanca (hook) ve thumbnail uzerine yazilacak kisa metin.
    hook: Mapped[str] = mapped_column(Text, nullable=False, default="")
    thumbnail_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Icerik bildirimleri (kanal modu + LLM karari sonucu donen deger).
    content_warning: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    ai_disclosure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_clip_metadata_status",
        ),
        default="draft",
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PublishedVideo(Base):
    """One uploaded clip on YouTube (M10).

    The (clip_candidate_id, orientation) pair structurally prevents
    duplicate uploads — a reaction video publishes both its vertical
    shorts and the horizontal full cut; the resumable session URI is
    kept so an interrupted upload can be reconciled instead of
    restarted from scratch. Horizontal full cuts carry a NULL
    candidate.
    """

    __tablename__ = "published_videos"
    __table_args__ = (
        UniqueConstraint(
            "clip_candidate_id", "orientation", name="uq_published_candidate_orientation"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("clip_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Yatay tam kesit satirlarinda kaynak video (klip satirlarinda NULL);
    # temizlik ve tek-yayin guvenligi icin dogrudan bag.
    source_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    orientation: Mapped[str] = mapped_column(
        String(12),
        CheckConstraint(
            "orientation IN ('vertical', 'horizontal')",
            name="ck_published_videos_orientation",
        ),
        default="vertical",
        nullable=False,
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    youtube_video_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_published_videos_visibility"
        ),
        default="private",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('uploading', 'uploaded', 'verified', 'failed')",
            name="ck_published_videos_status",
        ),
        default="uploading",
        nullable=False,
    )
    upload_session_uri: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Herkese acik yapilma ani: gizli yukleme ile yayin anini ayirir;
    # medya temizligi (retention) bu andan sayilir.
    public_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kullanicinin takvimden surukleyip yerlestirdigi yayin ani. NULL:
    # video slot mantigina uyar (yon bazli prime time saatleri).
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
