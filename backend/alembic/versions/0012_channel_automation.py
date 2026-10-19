"""channel automation state, stock target, content modes

The Start/Stop automation milestone: per-channel persistent automation
state (stopped/running/paused/error) with the horizontal stock target
(default 3) and the auto/on/off content modes (title/description/tags
generation, 18+ content warning, AI-use disclosure) plus the channel
system prompt; the channel_characters follow table; the 'confirmed'
terminal status for source videos (Shorts production finished — never
re-queued); 'whisper' as a transcript source; clip metadata notification
flags; and jobs.run_at for retry backoff.

Migrations target PostgreSQL (ADR-008); tests verify offline SQL.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- publishing_profiles: otomasyon durumu ve kanal ayarlari ---
    op.add_column(
        "publishing_profiles",
        sa.Column(
            "automation_state",
            sa.String(length=12),
            server_default="stopped",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_publishing_profiles_automation_state",
        "publishing_profiles",
        "automation_state IN ('stopped', 'running', 'paused', 'error')",
    )
    op.add_column(
        "publishing_profiles",
        sa.Column(
            "horizontal_stock_target",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    for mode_col in (
        "title_mode",
        "description_mode",
        "tags_mode",
        "content_warning_mode",
        "ai_disclosure_mode",
    ):
        op.add_column(
            "publishing_profiles",
            sa.Column(
                mode_col,
                sa.String(length=8),
                server_default="auto",
                nullable=False,
            ),
        )
        op.create_check_constraint(
            f"ck_publishing_profiles_{mode_col}",
            "publishing_profiles",
            f"{mode_col} IN ('auto', 'on', 'off')",
        )
    op.add_column(
        "publishing_profiles",
        sa.Column("channel_system_prompt", sa.Text(), nullable=True),
    )

    # --- channel_characters: kanalin takip ettigi karakterler ---
    op.create_table(
        "channel_characters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "character_id"),
    )

    # --- source_videos: 'confirmed' terminal durumu ---
    op.drop_constraint("ck_source_videos_status", "source_videos")
    op.create_check_constraint(
        "ck_source_videos_status",
        "source_videos",
        "status IN ('discovered', 'excluded', 'planned', 'processed', "
        "'confirmed')",
    )

    # --- transcripts: whisper kaynagi ---
    op.drop_constraint("ck_transcripts_source", "transcripts")
    op.create_check_constraint(
        "ck_transcripts_source",
        "transcripts",
        "source IN ('sidecar', 'auto_caption', 'whisper')",
    )

    # --- clip_metadata: icerik bildirim bayraklari ---
    op.add_column(
        "clip_metadata",
        sa.Column(
            "content_warning", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "clip_metadata",
        sa.Column(
            "ai_disclosure", sa.Boolean(), server_default="false", nullable=False
        ),
    )

    # --- jobs: yeniden deneme bekleme araligi ---
    op.add_column(
        "jobs", sa.Column("run_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("jobs", "run_at")
    op.drop_column("clip_metadata", "ai_disclosure")
    op.drop_column("clip_metadata", "content_warning")
    op.drop_constraint("ck_transcripts_source", "transcripts")
    op.create_check_constraint(
        "ck_transcripts_source",
        "transcripts",
        "source IN ('sidecar', 'auto_caption')",
    )
    op.drop_constraint("ck_source_videos_status", "source_videos")
    op.create_check_constraint(
        "ck_source_videos_status",
        "source_videos",
        "status IN ('discovered', 'excluded', 'planned', 'processed')",
    )
    # 'confirmed' satirlari geri donuste 'processed'e cekilir.
    op.execute("UPDATE source_videos SET status = 'processed'")
    op.drop_table("channel_characters")
    op.drop_column("publishing_profiles", "channel_system_prompt")
    for mode_col in (
        "ai_disclosure_mode",
        "content_warning_mode",
        "tags_mode",
        "description_mode",
        "title_mode",
    ):
        op.drop_constraint(
            f"ck_publishing_profiles_{mode_col}", "publishing_profiles"
        )
        op.drop_column("publishing_profiles", mode_col)
    op.drop_column("publishing_profiles", "horizontal_stock_target")
    op.drop_constraint(
        "ck_publishing_profiles_automation_state", "publishing_profiles"
    )
    op.drop_column("publishing_profiles", "automation_state")
