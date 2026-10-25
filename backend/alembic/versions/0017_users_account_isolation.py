"""users table + channels.owner_user_id (account isolation, madde 6)

Kullanıcı isteği 2026-10-25: stüdyo ileride farklı kullanıcılara
açılacağı için hesap izolasyonu şimdiden kurulur. Tek operatörlük
``app_meta.studio_auth`` döneminden gelen hesap admin olarak
``users`` tablosuna taşınır (studio_auth SİLİNMEZ; oturum imza
sırrı orada yaşamaya devam eder) ve mevcut kanallar ona bağlanır.

Sürüm notu: oturum çerezleri artık kullanıcı kimliği taşır
({uid, sub, ver, exp}); eski tek-kullanıcılık çerezleri bu
migration'dan sonra bir kez yeniden giriş ister.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-25

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.add_column(
        "channels",
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("channels") as batch:
        batch.create_foreign_key(
            "fk_channels_owner_user",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    _backfill_admin_from_studio_auth()


def _backfill_admin_from_studio_auth() -> None:
    """studio_auth'taki tek hesabı users'a admin olarak ekle ve tüm
    sahipsiz kanalları ona bağla. Idempotent: kullanıcı adı duruyorsa
    dokunmaz. Offline SQL üretiminde (--sql) sorgu çalıştırılamaz;
    geri-doldurma atlanır, canlı yükseltmede çalışır."""
    if context.is_offline_mode():
        return
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_meta WHERE key = 'studio_auth'")
    ).fetchone()
    if row is None:
        return
    raw = row[0]
    config = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(config, dict):
        return
    username = config.get("username")
    password_hash = config.get("password_hash")
    if not username or not password_hash:
        return
    existing = conn.execute(
        sa.text("SELECT id FROM users WHERE username = :u"), {"u": username}
    ).fetchone()
    if existing is None:
        conn.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, role, plan,"
                " is_active, token_version)"
                " VALUES (:u, :h, 'admin', 'pro', TRUE, 1)"
            ),
            {"u": username, "h": password_hash},
        )
        existing = conn.execute(
            sa.text("SELECT id FROM users WHERE username = :u"),
            {"u": username},
        ).fetchone()
    conn.execute(
        sa.text(
            "UPDATE channels SET owner_user_id = :uid WHERE owner_user_id IS NULL"
        ),
        {"uid": existing[0]},
    )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.drop_constraint("fk_channels_owner_user", type_="foreignkey")
    op.drop_column("channels", "owner_user_id")
    op.drop_table("users")
