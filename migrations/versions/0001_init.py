"""initial schema

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("prefix", sa.String, nullable=False, unique=True),
        sa.Column("key_hash", sa.String, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_table(
        "agents",
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False, server_default=""),
    )
    op.create_table(
        "end_users",
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("display_name", sa.String, nullable=False, server_default=""),
        sa.Column("profile_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("agent_id", sa.String, nullable=False),
        sa.Column("end_user_id", sa.String, nullable=False),
        sa.Column("idempotency_key", sa.String, nullable=False),
        sa.Column("task_id", sa.String, nullable=False),
        sa.Column("task_context", JSON, nullable=False),
        sa.Column("locale", sa.String),
        sa.Column("status", sa.String, nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_session_idempotency"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_session_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "end_user_id"], ["end_users.tenant_id", "end_users.id"]),
    )
    op.create_table(
        "profile_facts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("end_user_id", sa.String, nullable=False),
        sa.Column("source_session_id", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("value", JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("evidence", sa.Text),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("superseded_by", sa.String),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("provenance", JSON),
        sa.ForeignKeyConstraint(["tenant_id", "end_user_id"], ["end_users.tenant_id", "end_users.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "source_session_id"], ["sessions.tenant_id", "sessions.id"]),
    )
    op.create_index(
        "uq_one_current_fact", "profile_facts",
        ["tenant_id", "end_user_id", "category", "key"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index("ix_facts_user", "profile_facts", ["tenant_id", "end_user_id"])


def downgrade() -> None:
    for table in ("profile_facts", "sessions", "end_users", "agents", "api_keys", "tenants"):
        op.drop_table(table)
