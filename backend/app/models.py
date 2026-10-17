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
