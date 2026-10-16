"""initial application metadata table

Baseline schema: app_meta holds runtime key/value state (schema markers,
operational flags). Real domain models arrive in Milestone 3.

Revision ID: 0001
Revises:
Create Date: 2026-10-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_app_meta_updated_at", "app_meta", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_app_meta_updated_at", table_name="app_meta")
    op.drop_table("app_meta")
