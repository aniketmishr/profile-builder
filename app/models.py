from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index,
    Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    prefix: Mapped[str] = mapped_column(String, unique=True)
    key_hash: Mapped[str] = mapped_column(String)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")


class EndUser(Base):
    """One row per end user per tenant. This is the profile root."""
    __tablename__ = "end_users"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    profile_version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DebriefSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    end_user_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(String)
    task_context: Mapped[dict] = mapped_column(JsonType)
    locale: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_session_idempotency"),
        UniqueConstraint("tenant_id", "id", name="uq_session_tenant_id"),  # FK target for facts
        ForeignKeyConstraint(["tenant_id", "agent_id"], ["agents.tenant_id", "agents.id"]),
        ForeignKeyConstraint(["tenant_id", "end_user_id"], ["end_users.tenant_id", "end_users.id"]),
    )


class ProfileFact(Base):
    """Append-only. Exactly one row per (tenant, user, category, key) has is_current = true."""
    __tablename__ = "profile_facts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    end_user_id: Mapped[str] = mapped_column(String)
    source_session_id: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    value: Mapped[object] = mapped_column(JsonType)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provenance: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "end_user_id"], ["end_users.tenant_id", "end_users.id"]),
        ForeignKeyConstraint(["tenant_id", "source_session_id"], ["sessions.tenant_id", "sessions.id"]),
        Index(
            "uq_one_current_fact",
            "tenant_id", "end_user_id", "category", "key",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
        Index("ix_facts_user", "tenant_id", "end_user_id"),
    )


class Debrief(Base):
    """One per session: the persisted plan metadata and conversation state."""
    __tablename__ = "debriefs"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, default="active")  # active | complete
    end_reason: Mapped[str | None] = mapped_column(String, nullable=True)  # all_answered | question_cap | agent_ended
    plan_source: Mapped[str] = mapped_column(String)  # llm | fallback
    prompt_version: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_latency_ms: Mapped[float] = mapped_column(Float, default=0)
    plan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    )


class DebriefQuestion(Base):
    """status: pending | asked | answered | skipped | covered (answered by an earlier answer) | dropped (cap/ended)."""
    __tablename__ = "debrief_questions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    session_id: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String, default="planned")  # planned | follow_up
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", "seq", name="uq_debrief_question_seq"),
        ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )


class DebriefMessage(Base):
    """The transcript. meta holds why the AI did what it did (interpretation, prompt version, model)."""
    __tablename__ = "debrief_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    session_id: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)  # ai | agent
    text: Mapped[str] = mapped_column(Text, default="")
    question_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str | None] = mapped_column(String, nullable=True)  # answer | skip | end (agent messages)
    meta: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "session_id", "seq", name="uq_debrief_message_seq"),
        ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )


class Extraction(Base):
    """One per session. status: running | ready | confirmed | failed.
    llm_input/llm_output/dropped keep the exact prompt, the model's answer and what validation rejected,
    so 'why was this fact proposed' can always be answered."""
    __tablename__ = "extractions"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="running")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # llm | fallback | none
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_output: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    dropped: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "session_id"], ["debriefs.tenant_id", "debriefs.session_id"]),
    )


class ExtractedFact(Base):
    """A proposed fact awaiting the agent's decision. status: proposed | saved | discarded."""
    __tablename__ = "extracted_facts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    session_id: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    value: Mapped[object] = mapped_column(JsonType)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="proposed")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    original_value: Mapped[object | None] = mapped_column(JsonType, nullable=True)
    saved_fact_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "session_id"], ["extractions.tenant_id", "extractions.session_id"]),
        Index("ix_extracted_facts_session", "tenant_id", "session_id"),
    )
