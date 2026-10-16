from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "contact_preferences", "communication_style", "products_and_usage",
    "constraints", "pain_points", "personal_context", "notes",
]


# ---- sessions ---------------------------------------------------------------
class AgentIn(BaseModel):
    id: str = Field(min_length=1)
    name: str = ""


class EndUserIn(BaseModel):
    id: str = Field(min_length=1)
    display_name: str = ""


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="allow")  # the admin panel may extend the task context
    id: str = Field(min_length=1)
    type: str
    title: str = ""
    outcome: str | None = None
    channel: str | None = None
    duration_sec: int | None = None
    transcript_excerpt: str | None = None


class SessionCreate(BaseModel):
    idempotency_key: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    agent: AgentIn
    end_user: EndUserIn
    task: TaskIn
    locale: str | None = None

    model_config = ConfigDict(json_schema_extra={"example": {
        "idempotency_key": "task_8f3a21",
        "tenant_id": "tn_acme",
        "agent": {"id": "ag_104", "name": "Priya S."},
        "end_user": {"id": "eu_55021", "display_name": "Rahul M."},
        "task": {
            "id": "task_8f3a21", "type": "refund_dispute",
            "title": "Refund for damaged order #44871",
            "outcome": "resolved_partial_refund", "channel": "whatsapp", "duration_sec": 740,
            "transcript_excerpt": "...I keep getting emails but I never read them, just WhatsApp me...",
        },
        "locale": "en-IN",
    }})


class SessionOut(BaseModel):
    session_id: str
    status: str
    created: bool
    chat_url: str
    tenant_id: str
    agent_id: str
    end_user_id: str
    task_id: str
    created_at: datetime | None = None


# ---- facts / profiles -------------------------------------------------------
class FactIn(BaseModel):
    category: Category
    key: str = Field(min_length=1, max_length=100)
    value: Any
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None


class FactsIn(BaseModel):
    source_session_id: str
    facts: list[FactIn] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(json_schema_extra={"example": {
        "source_session_id": "ss_replace_with_real_id",
        "facts": [
            {"category": "contact_preferences", "key": "preferred_channel", "value": "whatsapp",
             "confidence": 0.95, "evidence": "only whatsapp"},
            {"category": "constraints", "key": "refund_preference", "value": "store_credit",
             "confidence": 0.9, "evidence": "store credit instead of refund"},
        ],
    }})


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category: str
    key: str
    value: Any
    confidence: float
    evidence: str | None
    source_session_id: str
    captured_at: datetime
    is_current: bool
    superseded_by: str | None = None
    provenance: dict | None = None


class FactsWritten(BaseModel):
    written: list[FactOut]
    unchanged: list[FactOut]
    profile_version: int


class ProfileOut(BaseModel):
    end_user_id: str
    tenant_id: str
    display_name: str
    profile_version: int
    updated_at: datetime | None
    facts: list[FactOut]


class SessionRef(BaseModel):
    session_id: str
    task_id: str
    task_type: str | None
    task_title: str | None
    agent_id: str
    created_at: datetime | None


class FactHistory(BaseModel):
    category: str
    key: str
    versions: list[FactOut]  # oldest first; the last one is current


class HistoryOut(BaseModel):
    end_user_id: str
    tenant_id: str
    history: list[FactHistory]
    sessions: list[SessionRef]


class ContextOut(BaseModel):
    end_user_id: str
    context: str
    approx_tokens: int
    truncated: bool
