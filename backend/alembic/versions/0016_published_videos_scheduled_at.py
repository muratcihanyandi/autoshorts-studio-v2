"""published_videos.scheduled_at: manual calendar scheduling

Kullanıcı isteği 2026-10-23: takvimdeki videolar sürükle-bırak ile günün
herhangi bir saatine elle yerleştirilebilsin. Gizli yüklenmiş (verified,
private) videonun herkese açılma anı bu kolonda taşınır; NULL olduğu
sürece video yön bazlı prime time slot mantığına uyar.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "published_videos",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("published_videos", "scheduled_at")
