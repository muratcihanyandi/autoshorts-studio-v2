"""characters and render orientation

Milestone 13: streamer characters (photo + reference face + per-character
system prompt), multi-platform sources (youtube/twitch/kick with reaction
flag and head/tail trim), the render orientation dimension (vertical
shorts vs trimmed horizontal full cuts), and metadata hook/thumbnail text.
Duplicate-prevention uniques on rendered_clips and published_videos move
from clip_candidate_id alone to (clip_candidate_id, orientation).
Migrations target PostgreSQL (ADR-008); tests verify offline SQL.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("photo_path", sa.String(length=255), nullable=True),
        sa.Column("reference_face_path", sa.String(length=255), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.add_column(
        "source_channels",
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "source_channels",
        sa.Column(
            "platform",
            sa.String(length=16),
            server_default="youtube",
            nullable=False,
        ),
    )
    op.add_column(
        "source_channels",
        sa.Column(
            "reaction_source",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "source_channels",
        sa.Column(
            "trim_start_seconds", sa.Float(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "source_channels",
        sa.Column(
            "trim_end_seconds", sa.Float(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_source_channels_platform",
        "source_channels",
        "platform IN ('youtube', 'twitch', 'kick')",
    )

    op.add_column(
        "rendered_clips",
        sa.Column(
            "source_video_id",
            sa.Integer(),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "rendered_clips",
        sa.Column(
            "orientation",
            sa.String(length=12),
            server_default="vertical",
            nullable=False,
        ),
    )
    op.add_column(
        "rendered_clips",
        sa.Column("thumbnail_path", sa.String(length=255), nullable=True),
    )
    op.alter_column("rendered_clips", "clip_candidate_id", nullable=True)
    op.drop_constraint("uq_rendered_clips_candidate", "rendered_clips", type_="unique")
    op.create_unique_constraint(
        "uq_rendered_clip_candidate_orientation",
        "rendered_clips",
        ["clip_candidate_id", "orientation"],
    )
    op.create_check_constraint(
        "ck_rendered_clips_orientation",
        "rendered_clips",
        "orientation IN ('vertical', 'horizontal')",
    )

    op.add_column(
        "clip_metadata",
        sa.Column(
            "source_video_id",
            sa.Integer(),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.alter_column("clip_metadata", "clip_candidate_id", nullable=True)
    op.add_column(
        "clip_metadata", sa.Column("hook", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "clip_metadata",
        sa.Column("thumbnail_text", sa.Text(), server_default="", nullable=False),
    )

    op.add_column(
        "published_videos",
        sa.Column(
            "orientation",
            sa.String(length=12),
            server_default="vertical",
            nullable=False,
        ),
    )
    op.alter_column("published_videos", "clip_candidate_id", nullable=True)
    op.drop_constraint(
        "uq_published_videos_candidate", "published_videos", type_="unique"
    )
    op.create_unique_constraint(
        "uq_published_candidate_orientation",
        "published_videos",
        ["clip_candidate_id", "orientation"],
    )
    op.create_check_constraint(
        "ck_published_videos_orientation",
        "published_videos",
        "orientation IN ('vertical', 'horizontal')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_published_videos_orientation", "published_videos", type_="check"
    )
    op.drop_constraint(
        "uq_published_candidate_orientation", "published_videos", type_="unique"
    )
    # Dikey olmayan satirlar kaldirilmadan geri donus desteklenmez.
    op.execute("DELETE FROM published_videos WHERE orientation != 'vertical'")
    op.alter_column("published_videos", "clip_candidate_id", nullable=False)
    op.create_unique_constraint(
        "uq_published_videos_candidate", "published_videos", ["clip_candidate_id"]
    )
    op.drop_column("published_videos", "orientation")

    op.drop_column("clip_metadata", "thumbnail_text")
    op.drop_column("clip_metadata", "hook")
    op.execute(
        "DELETE FROM clip_metadata WHERE clip_candidate_id IS NULL"
    )
    op.alter_column("clip_metadata", "clip_candidate_id", nullable=False)
    op.drop_column("clip_metadata", "source_video_id")

    op.drop_constraint("ck_rendered_clips_orientation", "rendered_clips", type_="check")
    op.drop_constraint(
        "uq_rendered_clip_candidate_orientation", "rendered_clips", type_="unique"
    )
    op.execute("DELETE FROM rendered_clips WHERE orientation != 'vertical'")
    op.alter_column("rendered_clips", "clip_candidate_id", nullable=False)
    op.create_unique_constraint(
        "uq_rendered_clips_candidate", "rendered_clips", ["clip_candidate_id"]
    )
    op.drop_column("rendered_clips", "thumbnail_path")
    op.drop_column("rendered_clips", "orientation")
    op.drop_column("rendered_clips", "source_video_id")

    op.drop_constraint(
        "ck_source_channels_platform", "source_channels", type_="check"
    )
    op.drop_column("source_channels", "trim_end_seconds")
    op.drop_column("source_channels", "trim_start_seconds")
    op.drop_column("source_channels", "reaction_source")
    op.drop_column("source_channels", "platform")
    op.drop_column("source_channels", "character_id")

    op.drop_table("characters")
