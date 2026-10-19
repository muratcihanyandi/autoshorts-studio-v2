"""subtitle corrections, metadata templates, clip metadata

Milestone 9: LLM-corrected transcripts parallel to the originals,
per-channel metadata templates, and append-only clip metadata
revisions.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corrected_transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "media_asset_id",
            sa.Integer(),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segments", postgresql.JSONB(), nullable=False),
        sa.Column("corrected_count", sa.Integer(), nullable=False),
        sa.Column("flagged_count", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_asset_id", name="uq_corrected_transcripts_asset"
        ),
    )
    op.create_table(
        "metadata_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title_pattern", sa.Text(), nullable=False),
        sa.Column("description_pattern", sa.Text(), nullable=False),
        sa.Column("base_tags", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", name="uq_metadata_templates_channel"),
    )
    op.create_table(
        "clip_metadata",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "clip_candidate_id",
            sa.Integer(),
            sa.ForeignKey("clip_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_candidate_id", "revision", name="uq_clip_metadata_rev"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_clip_metadata_status",
        ),
    )
    op.create_index(
        "ix_clip_metadata_clip_candidate_id", "clip_metadata", ["clip_candidate_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_clip_metadata_clip_candidate_id", table_name="clip_metadata"
    )
    op.drop_table("clip_metadata")
    op.drop_table("metadata_templates")
    op.drop_table("corrected_transcripts")
