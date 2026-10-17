"""source videos + daily quota usage

Milestone 4: discovered source videos (duplicate-guarded per source) and
the YouTube Data API daily quota ledger.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_channel_id", sa.Integer(), nullable=False),
        sa.Column("youtube_video_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "discovered_at",
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
        sa.CheckConstraint(
            "status IN ('discovered', 'excluded', 'planned', 'processed')",
            name="ck_source_videos_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_channel_id"], ["source_channels.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_channel_id", "youtube_video_id", name="uq_source_video_per_source"
        ),
    )
    op.create_index(
        "ix_source_videos_source_channel_id", "source_videos", ["source_channel_id"]
    )

    op.create_table(
        "quota_usage",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("units_used", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("quota_usage")
    op.drop_index(
        "ix_source_videos_source_channel_id", table_name="source_videos"
    )
    op.drop_table("source_videos")
