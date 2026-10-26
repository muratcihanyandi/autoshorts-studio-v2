"""published_videos partial unique index for horizontal full-cuts + jobs claim index

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Yatay tam kesit tekillik koruması (Audit 3.5)
    op.create_index(
        "uq_published_full_cut",
        "published_videos",
        ["source_video_id", "orientation"],
        unique=True,
        postgresql_where=sa.text("clip_candidate_id IS NULL"),
        sqlite_where=sa.text("clip_candidate_id IS NULL"),
    )

    # 2. İş kuyruğu claim performans indeksi (Audit 8.5)
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "priority", "id"],
        postgresql_where=sa.text("status = 'queued'"),
        sqlite_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_index("uq_published_full_cut", table_name="published_videos")
