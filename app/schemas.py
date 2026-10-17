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


# ---- debrief planning (dev preview) -----------------------------------------
class PlannedQuestionOut(BaseModel):
    id: str
    category: Category
    text: str
    why: str = ""


class PlanPreviewOut(BaseModel):
    session_id: str
    source: Literal["llm", "fallback"]
    provider: str | None
    model: str | None
    prompt_version: str
    latency_ms: float
    error: str | None = None
    intro: str
    questions: list[PlannedQuestionOut]


# ---- debrief conversation ---------------------------------------------------
class AnswerIn(BaseModel):
    question_id: str = Field(description="id of the question being answered (the current one)")
    action: Literal["answer", "skip", "end"] = "answer"
    text: str | None = Field(default=None, max_length=2000)
    voice_note_id: str | None = Field(default=None, description="set when the text came from a voice note's transcript")

    model_config = ConfigDict(json_schema_extra={"example": {
        "question_id": "dq_replace_with_current_question_id", "action": "answer",
        "text": "he said never email him, only whatsapp, and not after 9pm",
    }})


class DebriefMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    seq: int
    role: Literal["ai", "agent"]
    text: str
    question_id: str | None
    action: str | None
    created_at: datetime | None


class DebriefQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    seq: int
    category: str
    text: str
    kind: str
    status: str


class DebriefProgress(BaseModel):
    asked: int
    cap: int


class DebriefStateOut(BaseModel):
    session_id: str
    state: Literal["not_started", "active", "complete"]
    end_reason: str | None = None
    plan_source: str | None = None
    current_question_id: str | None = None
    progress: DebriefProgress
    voice_enabled: bool = False
    questions: list[DebriefQuestionOut]
    messages: list[DebriefMessageOut]


# ---- extraction and confirmation --------------------------------------------
FactValue = str | list[str]


class ExtractedFactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category: str
    key: str
    value: Any
    confidence: float
    evidence: str
    status: Literal["proposed", "saved", "discarded"]
    edited: bool = False


class ExtractionOut(BaseModel):
    session_id: str
    status: Literal["running", "ready", "confirmed", "failed"]
    source: str | None = None  # llm | fallback | none
    prompt_version: str | None = None
    model: str | None = None
    error: str | None = None
    attempt: int
    dropped_count: int = 0
    facts: list[ExtractedFactOut]


class DecisionIn(BaseModel):
    fact_id: str
    action: Literal["keep", "edit", "discard"]
    value: FactValue | None = Field(default=None, description="new value; required for action 'edit'")


class ConfirmIn(BaseModel):
    decisions: list[DecisionIn] = Field(
        default_factory=list, max_length=50,
        description="Facts not listed are kept. Send {} to save everything as proposed.",
    )

    model_config = ConfigDict(json_schema_extra={"example": {"decisions": [
        {"fact_id": "xf_replace", "action": "edit", "value": "21:30 local"},
        {"fact_id": "xf_replace_2", "action": "discard"},
    ]}})


class ConfirmOut(BaseModel):
    saved: list[FactOut]
    unchanged: list[FactOut]
    discarded: int
    profile_version: int


# ---- voice ------------------------------------------------------------------
class VoiceNoteOut(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    question_id: str
    transcript: str | None = None
    error: str | None = None
    attempt: int
    size_bytes: int
    duration_ms: int | None = None
