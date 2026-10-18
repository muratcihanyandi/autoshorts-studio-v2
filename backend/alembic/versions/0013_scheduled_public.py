"""daily horizontal limit, public_at, media retention default

Scheduled-public milestone: approved clips upload to YouTube as private
immediately on approval; the scheduled slot flips them public. The
published_videos row gains public_at (the moment the video became
public — the anchor for media retention) and publishing_profiles gains
daily_horizontal_limit (the daily publish cap for horizontal full cuts;
verticals keep using daily_clip_target). The runtime setting
media_retention_days (0 = clean right after going public, N = N days
after, -1 = never) is the site-level media cleanup policy.

Migrations target PostgreSQL (ADR-008); tests verify offline SQL.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publishing_profiles",
        sa.Column(
            "daily_horizontal_limit",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.add_column(
        "published_videos",
        sa.Column("public_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Yatay tam kesit satirlarinda dogrudan kaynak bagintisi (klip
    # satirlarinda NULL); eski satirlar NULL kalir.
    op.add_column(
        "published_videos",
        sa.Column("source_video_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_published_videos_source_video",
        "published_videos",
        "source_videos",
        ["source_video_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_published_videos_source_video_id",
        "published_videos",
        ["source_video_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_published_videos_source_video_id", table_name="published_videos"
    )
    op.drop_constraint(
        "fk_published_videos_source_video", "published_videos", type_="foreignkey"
    )
    op.drop_column("published_videos", "source_video_id")
    op.drop_column("published_videos", "public_at")
    op.drop_column("publishing_profiles", "daily_horizontal_limit")
