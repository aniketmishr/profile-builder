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
