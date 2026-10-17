"""extraction: runs and proposed facts

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "extractions",
        sa.Column("tenant_id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, primary_key=True),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source", sa.String),
        sa.Column("prompt_version", sa.String),
        sa.Column("model", sa.String),
        sa.Column("error", sa.Text),
        sa.Column("llm_input", sa.Text),
        sa.Column("llm_output", JSON),
        sa.Column("dropped", JSON),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )
    op.create_table(
        "extracted_facts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("value", JSON, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="proposed"),
        sa.Column("edited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("original_value", JSON),
        sa.Column("saved_fact_id", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["extractions.tenant_id", "extractions.session_id"]),
    )
    op.create_index("ix_extracted_facts_session", "extracted_facts", ["tenant_id", "session_id"])


def downgrade() -> None:
    op.drop_table("extracted_facts")
    op.drop_table("extractions")
