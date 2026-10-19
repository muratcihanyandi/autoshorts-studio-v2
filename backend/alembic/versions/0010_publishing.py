"""published videos store

Milestone 10: uploaded clip records with YouTube video IDs, private
visibility, resumable session URIs for reconciliation, and structural
duplicate prevention (unique clip_candidate_id).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "published_videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "clip_candidate_id",
            sa.Integer(),
            sa.ForeignKey("clip_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("youtube_video_id", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("upload_session_uri", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "clip_candidate_id", name="uq_published_videos_candidate"
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_published_videos_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'uploaded', 'verified', 'failed')",
            name="ck_published_videos_status",
        ),
    )
    op.create_index(
        "ix_published_videos_channel_id", "published_videos", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_published_videos_channel_id", table_name="published_videos"
    )
    op.drop_table("published_videos")
