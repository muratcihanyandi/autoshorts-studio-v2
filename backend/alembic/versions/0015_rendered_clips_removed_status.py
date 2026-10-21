"""rendered_clips: 'removed' status (clip removal feature)

Kullanıcı isteği 2026-10-21: hazır klipler arayüzden kaldırılabilsin;
gizli yüklenmişse önce YouTube'dan silinir. Render satırı 'removed'
mezartaşı olur — render/yükleme/metaveri beslemeleri status='rendered'
istediğinden klip yeniden üretilmez; aday ve hype seçimi korunur.

Migrations target PostgreSQL (ADR-008); tests verify offline SQL.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_rendered_clips_status", "rendered_clips", type_="check"
    )
    op.create_check_constraint(
        "ck_rendered_clips_status",
        "rendered_clips",
        "status IN ('rendering', 'rendered', 'review', 'failed',"
        " 'removed')",
    )


def downgrade() -> None:
    # Mezartaslar geriye uyumluluk icin 'failed'e doner.
    op.execute(
        "UPDATE rendered_clips SET status = 'failed'"
        " WHERE status = 'removed'"
    )
    op.drop_constraint(
        "ck_rendered_clips_status", "rendered_clips", type_="check"
    )
    op.create_check_constraint(
        "ck_rendered_clips_status",
        "rendered_clips",
        "status IN ('rendering', 'rendered', 'review', 'failed')",
    )
