"""voice notes: recorded answers and their transcription jobs

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_notes",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("question_id", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("audio", sa.LargeBinary),
        sa.Column("transcript", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("provider", sa.String),
        sa.Column("model", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )
    op.create_index("ix_voice_notes_session", "voice_notes", ["tenant_id", "session_id"])


def downgrade() -> None:
    op.drop_table("voice_notes")
