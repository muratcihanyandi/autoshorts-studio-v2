"""source filter rules + planning decisions

Milestone 4: per-source exclusion rules (JSONB) and the durable,
auditable planning ledger. One planning decision per source video
(unique) — repeated planning never duplicates.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_channels",
        sa.Column(
            "filter_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "planning_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_video_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('planned', 'skipped')",
            name="ck_planning_decisions_decision",
        ),
        sa.ForeignKeyConstraint(
            ["source_video_id"], ["source_videos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_video_id"),
    )
    op.create_index(
        "ix_planning_decisions_source_video_id",
        "planning_decisions",
        ["source_video_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_planning_decisions_source_video_id", table_name="planning_decisions"
    )
    op.drop_table("planning_decisions")
    op.drop_column("source_channels", "filter_rules")
