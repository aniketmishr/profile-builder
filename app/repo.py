"""The ONLY module that queries tenant data.

Every query goes through ScopedRepo, which is built from the tenant resolved from the
API key. Methods never accept a tenant_id, so a handler cannot forget it or pass the
wrong one. Composite foreign keys in the schema back this up at the database level.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Agent, ApiKey, Debrief, DebriefMessage, DebriefQuestion, DebriefSession, EndUser, ExtractedFact,
    Extraction, ProfileFact, VoiceNote,
)
from app.security import keys_match, parse_prefix


def find_tenant_for_key(db: Session, full_key: str) -> str | None:
    """Resolve an API key to a tenant id. The only query that runs before a tenant is known."""
    prefix = parse_prefix(full_key)
    if not prefix:
        return None
    row = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalar_one_or_none()
    if row is None or row.revoked_at is not None or not keys_match(full_key, row.key_hash):
        return None
    return row.tenant_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScopedRepo:
    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    def _select(self, model):
        return select(model).where(model.tenant_id == self.tenant_id)

    def commit(self) -> None:
        self.db.commit()

    # ---- agents / end users -------------------------------------------------
    def get_agent(self, agent_id: str) -> Agent | None:
        return self.db.execute(self._select(Agent).where(Agent.id == agent_id)).scalar_one_or_none()

    def upsert_agent(self, agent_id: str, name: str) -> Agent:
        row = self.db.execute(self._select(Agent).where(Agent.id == agent_id)).scalar_one_or_none()
        if row is None:
            try:
                with self.db.begin_nested():
                    row = Agent(tenant_id=self.tenant_id, id=agent_id, name=name)
                    self.db.add(row)
            except IntegrityError:  # lost a race with a concurrent insert
                row = self.db.execute(self._select(Agent).where(Agent.id == agent_id)).scalar_one()
        elif name and row.name != name:
            row.name = name
        return row

    def upsert_end_user(self, end_user_id: str, display_name: str) -> EndUser:
        row = self.get_end_user(end_user_id)
        if row is None:
            try:
                with self.db.begin_nested():
                    row = EndUser(tenant_id=self.tenant_id, id=end_user_id, display_name=display_name)
                    self.db.add(row)
            except IntegrityError:
                row = self.get_end_user(end_user_id)
        elif display_name and row.display_name != display_name:
            row.display_name = display_name
        return row

    def get_end_user(self, end_user_id: str, lock: bool = False) -> EndUser | None:
        q = self._select(EndUser).where(EndUser.id == end_user_id)
        if lock:
            q = q.with_for_update()  # no-op on SQLite
        return self.db.execute(q).scalar_one_or_none()

    # ---- sessions -----------------------------------------------------------
    def get_session(self, session_id: str) -> DebriefSession | None:
        q = self._select(DebriefSession).where(DebriefSession.id == session_id)
        return self.db.execute(q).scalar_one_or_none()

    def get_session_by_key(self, idempotency_key: str) -> DebriefSession | None:
        q = self._select(DebriefSession).where(DebriefSession.idempotency_key == idempotency_key)
        return self.db.execute(q).scalar_one_or_none()

    def sessions_by_ids(self, ids: set[str]) -> list[DebriefSession]:
        if not ids:
            return []
        q = self._select(DebriefSession).where(DebriefSession.id.in_(ids)).order_by(DebriefSession.created_at)
        return list(self.db.execute(q).scalars())

    def insert_session(self, **fields) -> DebriefSession:
        """Insert in a savepoint so a unique-key collision doesn't poison the transaction."""
        row = DebriefSession(tenant_id=self.tenant_id, **fields)
        with self.db.begin_nested():
            self.db.add(row)
        return row

    # ---- facts --------------------------------------------------------------
    def current_fact(self, end_user_id: str, category: str, key: str) -> ProfileFact | None:
        q = self._select(ProfileFact).where(
            ProfileFact.end_user_id == end_user_id,
            ProfileFact.category == category,
            ProfileFact.key == key,
            ProfileFact.is_current.is_(True),
        ).with_for_update()
        return self.db.execute(q).scalar_one_or_none()

    def current_facts(self, end_user_id: str) -> list[ProfileFact]:
        q = self._select(ProfileFact).where(
            ProfileFact.end_user_id == end_user_id, ProfileFact.is_current.is_(True)
        ).order_by(ProfileFact.category, ProfileFact.key)
        return list(self.db.execute(q).scalars())

    def all_facts(self, end_user_id: str) -> list[ProfileFact]:
        q = self._select(ProfileFact).where(ProfileFact.end_user_id == end_user_id).order_by(
            ProfileFact.category, ProfileFact.key, ProfileFact.captured_at, ProfileFact.id
        )
        return list(self.db.execute(q).scalars())

    def supersede(self, old: ProfileFact, new_id: str) -> None:
        old.is_current = False
        old.superseded_by = new_id
        old.superseded_at = _now()
        self.db.flush()  # free the "one current row" slot before the replacement is inserted

    def add_fact(self, **fields) -> ProfileFact:
        row = ProfileFact(tenant_id=self.tenant_id, captured_at=_now(), **fields)
        self.db.add(row)
        self.db.flush()
        return row

    def touch_profile(self, end_user: EndUser) -> None:
        end_user.profile_version = (end_user.profile_version or 0) + 1
        end_user.updated_at = _now()

    # ---- debrief ------------------------------------------------------------
    def get_debrief(self, session_id: str, lock: bool = False) -> Debrief | None:
        q = self._select(Debrief).where(Debrief.session_id == session_id)
        if lock:
            q = q.with_for_update()  # serialises turns for one session (no-op on SQLite)
        return self.db.execute(q).scalar_one_or_none()

    def create_debrief(self, session_id: str, meta: dict, questions: list[dict]) -> Debrief:
        """Plan + questions in one savepoint. Raises IntegrityError if the debrief already exists."""
        with self.db.begin_nested():
            debrief = Debrief(tenant_id=self.tenant_id, session_id=session_id, state="active", **meta)
            self.db.add(debrief)
            for i, q in enumerate(questions, start=1):
                self.db.add(DebriefQuestion(
                    id=new_id("dq"), tenant_id=self.tenant_id, session_id=session_id,
                    seq=i, kind="planned", status="pending", **q,
                ))
        return debrief

    def debrief_questions(self, session_id: str) -> list[DebriefQuestion]:
        q = self._select(DebriefQuestion).where(DebriefQuestion.session_id == session_id).order_by(DebriefQuestion.seq)
        return list(self.db.execute(q).scalars())

    def debrief_messages(self, session_id: str) -> list[DebriefMessage]:
        q = self._select(DebriefMessage).where(DebriefMessage.session_id == session_id).order_by(DebriefMessage.seq)
        return list(self.db.execute(q).scalars())

    def add_debrief_question(self, session_id: str, **fields) -> DebriefQuestion:
        row = DebriefQuestion(id=new_id("dq"), tenant_id=self.tenant_id, session_id=session_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row

    def add_debrief_message(self, session_id: str, **fields) -> DebriefMessage:
        row = DebriefMessage(id=new_id("dm"), tenant_id=self.tenant_id, session_id=session_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row

    # ---- extraction ---------------------------------------------------------
    def get_extraction(self, session_id: str, lock: bool = False) -> Extraction | None:
        q = self._select(Extraction).where(Extraction.session_id == session_id)
        if lock:
            q = q.with_for_update()
        return self.db.execute(q).scalar_one_or_none()

    def create_extraction(self, session_id: str) -> Extraction:
        """Claims the single extraction slot for a session. Raises IntegrityError if it already exists."""
        row = Extraction(tenant_id=self.tenant_id, session_id=session_id, status="running", attempt=1)
        with self.db.begin_nested():
            self.db.add(row)
        return row

    def extracted_facts(self, session_id: str) -> list[ExtractedFact]:
        q = self._select(ExtractedFact).where(ExtractedFact.session_id == session_id).order_by(
            ExtractedFact.created_at, ExtractedFact.id)
        return list(self.db.execute(q).scalars())

    def add_extracted_fact(self, session_id: str, **fields) -> ExtractedFact:
        row = ExtractedFact(id=new_id("xf"), tenant_id=self.tenant_id, session_id=session_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row

    def delete_extracted_facts(self, session_id: str) -> None:
        for row in self.extracted_facts(session_id):
            self.db.delete(row)
        self.db.flush()

    # ---- voice --------------------------------------------------------------
    def create_voice_note(self, session_id: str, **fields) -> VoiceNote:
        row = VoiceNote(id=new_id("vn"), tenant_id=self.tenant_id, session_id=session_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row

    def get_voice_note(self, note_id: str, session_id: str | None = None, lock: bool = False) -> VoiceNote | None:
        q = self._select(VoiceNote).where(VoiceNote.id == note_id)
        if session_id is not None:
            q = q.where(VoiceNote.session_id == session_id)
        if lock:
            q = q.with_for_update()
        return self.db.execute(q).scalar_one_or_none()

    def count_voice_notes(self, session_id: str) -> int:
        q = select(func.count()).select_from(VoiceNote).where(
            VoiceNote.tenant_id == self.tenant_id, VoiceNote.session_id == session_id)
        return self.db.execute(q).scalar_one()
