"""media pipeline tables

Milestone 7: downloaded assets with stage-gated progress, ffprobe
inspections, transcripts, and scored clip candidates. The unique
source_video_id on media_assets plus the stage column make the
pipeline idempotent under job retries.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "source_video_id",
            sa.Integer(),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_video_id", name="uq_media_assets_source_video"),
        sa.CheckConstraint(
            "origin IN ('youtube', 'local_import')", name="ck_media_assets_origin"
        ),
        sa.CheckConstraint(
            "status IN ('downloading', 'downloaded', 'inspected', 'transcribed', "
            "'analyzed', 'processed', 'failed')",
            name="ck_media_assets_status",
        ),
        sa.CheckConstraint(
            "stage IN ('download', 'inspect', 'transcript', 'analysis', 'candidates')",
            name="ck_media_assets_stage",
        ),
    )
    op.create_table(
        "media_inspections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "media_asset_id",
            sa.Integer(),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("video_codec", sa.Text(), nullable=False),
        sa.Column("audio_codec", sa.Text(), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=False),
        sa.Column("format_name", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", name="uq_media_inspections_asset"),
        sa.CheckConstraint(
            "duration_seconds > 0", name="ck_media_inspections_duration"
        ),
    )
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "media_asset_id",
            sa.Integer(),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("segments", postgresql.JSONB(), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", name="uq_transcripts_asset"),
        sa.CheckConstraint("source IN ('sidecar', 'auto_caption')", name="ck_transcripts_source"),
    )
    op.create_table(
        "clip_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "source_video_id",
            sa.Integer(),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duplicate_of_candidate_id", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_seconds > start_seconds", name="ck_clip_candidates_range"),
        sa.CheckConstraint(
            "status IN ('candidate', 'rejected', 'selected')",
            name="ck_clip_candidates_status",
        ),
    )
    op.create_index(
        "ix_clip_candidates_source_video_id", "clip_candidates", ["source_video_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_clip_candidates_source_video_id", table_name="clip_candidates"
    )
    op.drop_table("clip_candidates")
    op.drop_table("transcripts")
    op.drop_table("media_inspections")
    op.drop_table("media_assets")
