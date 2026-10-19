"""source output orientation (auto / vertical / horizontal)

Task-2 milestone: sources gained an explicit output orientation. 'auto'
keeps the legacy behavior (the reaction_source flag decides whether a
trimmed horizontal full cut is produced), 'vertical' produces vertical
shorts only — the downloaded horizontal file is deleted once the source
is confirmed — and 'horizontal' produces the full cut regardless of the
reaction flag. The ready-stock refill gate also moves from "processed
horizontal sources" to "ready unpublished clips"; no column change is
needed for that, only code.

Migrations target PostgreSQL (ADR-008); tests verify offline SQL.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_channels",
        sa.Column(
            "output_orientation",
            sa.String(length=12),
            server_default="auto",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_source_channels_output_orientation",
        "source_channels",
        "output_orientation IN ('auto', 'vertical', 'horizontal')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_source_channels_output_orientation",
        "source_channels",
        type_="check",
    )
    op.drop_column("source_channels", "output_orientation")
