"""llm provider chain and request logs

Milestone 5: up to three LLM providers with Fernet-encrypted API keys
and a bounded-fallback chain (ADR-011). Every provider attempt is
logged with a status category and latency, grouped by request UUID.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("provider_type", sa.String(length=16), nullable=False),
        sa.Column("api_base", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint("name"),
        sa.CheckConstraint(
            "provider_type IN ('openai', 'anthropic', 'google')",
            name="ck_llm_providers_type",
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 3", name="ck_llm_providers_retries"
        ),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 300", name="ck_llm_providers_timeout"
        ),
    )

    op.create_table(
        "llm_request_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["llm_providers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_request_logs_request_id", "llm_request_logs", ["request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_request_logs_request_id", table_name="llm_request_logs")
    op.drop_table("llm_request_logs")
    op.drop_table("llm_providers")
