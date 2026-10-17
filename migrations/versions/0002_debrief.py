"""debrief tables: plan metadata, questions, messages

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "debriefs",
        sa.Column("tenant_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, primary_key=True),
        sa.Column("state", sa.String, nullable=False, server_default="active"),
        sa.Column("end_reason", sa.String),
        sa.Column("plan_source", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("model", sa.String),
        sa.Column("plan_latency_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("plan_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    )
    op.create_table(
        "debrief_questions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("why", sa.Text, nullable=False, server_default=""),
        sa.Column("kind", sa.String, nullable=False, server_default="planned"),
        sa.Column("parent_id", sa.String),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "session_id", "seq", name="uq_debrief_question_seq"),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )
    op.create_table(
        "debrief_messages",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("question_id", sa.String),
        sa.Column("action", sa.String),
        sa.Column("meta", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "session_id", "seq", name="uq_debrief_message_seq"),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )


def downgrade() -> None:
    for table in ("debrief_messages", "debrief_questions", "debriefs"):
        op.drop_table(table)
