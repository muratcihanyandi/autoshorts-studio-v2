"""webcam calibration + rendered clips

Milestone 8: per-source webcam calibration (manual region or
confidence override) and the rendered_clips store for 9:16 outputs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webcam_calibrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "source_channel_id",
            sa.Integer(),
            sa.ForeignKey("source_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region_x", sa.Integer(), nullable=False),
        sa.Column("region_y", sa.Integer(), nullable=False),
        sa.Column("region_w", sa.Integer(), nullable=False),
        sa.Column("region_h", sa.Integer(), nullable=False),
        sa.Column("manual", sa.Boolean(), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_channel_id", name="uq_webcam_calibrations_source"
        ),
        sa.CheckConstraint(
            "min_confidence IS NULL OR (min_confidence >= 0 AND min_confidence <= 1)",
            name="ck_webcam_calibrations_confidence",
        ),
    )
    op.create_table(
        "rendered_clips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "clip_candidate_id",
            sa.Integer(),
            sa.ForeignKey("clip_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=True),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("webcam_region", postgresql.JSONB(), nullable=True),
        sa.Column("webcam_confidence", sa.Float(), nullable=False),
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
        sa.UniqueConstraint(
            "clip_candidate_id", name="uq_rendered_clips_candidate"
        ),
        sa.CheckConstraint(
            "status IN ('rendering', 'rendered', 'review', 'failed')",
            name="ck_rendered_clips_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("rendered_clips")
    op.drop_table("webcam_calibrations")
