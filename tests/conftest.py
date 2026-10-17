import os
import tempfile

# Must be set before the app is imported.
_db_file = os.path.join(tempfile.mkdtemp(), "test.db")
# Set TEST_DATABASE_URL to run the suite against Postgres (use an empty database).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_file}"
os.environ["SESSION_TOKEN_SECRET"] = "test-secret"
os.environ["ENABLE_DEBUG_ENDPOINTS"] = "true"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["PRECOMPUTE_PLANS"] = "false"  # tests opt in explicitly
os.environ["LLM_PROVIDER"] = "none"

import pytest
from fastapi.testclient import TestClient

from app.db import _sessionmaker, get_engine
from app.ids import new_id
from app.main import app
from app.models import Agent, ApiKey, Base, EndUser, Tenant
from app.security import generate_api_key


@pytest.fixture(scope="session")
def keys():
    """Two tenants, each with one agent and an end user that has the SAME id in both."""
    Base.metadata.create_all(get_engine())
    out = {}
    db = _sessionmaker()()
    for tid in ("tn_a", "tn_b"):
        db.add(Tenant(id=tid, name=tid))
        db.flush()
        db.add(Agent(tenant_id=tid, id="ag_1", name="Agent"))
        db.add(EndUser(tenant_id=tid, id="eu_1", display_name=f"User of {tid}"))
        full, prefix, h = generate_api_key()
        db.add(ApiKey(id=new_id("ak"), tenant_id=tid, prefix=prefix, key_hash=h))
        out[tid] = full
    db.commit()
    db.close()
    return out


@pytest.fixture(scope="session")
def client(keys):
    return TestClient(app)


def headers(key: str) -> dict:
    return {"X-API-Key": key}


def session_body(tenant: str, task: str = "task_1", user: str = "eu_1", key: str | None = None) -> dict:
    return {
        "idempotency_key": key or task,
        "tenant_id": tenant,
        "agent": {"id": "ag_1", "name": "Agent"},
        "end_user": {"id": user, "display_name": f"User of {tenant}"},
        "task": {"id": task, "type": "refund_dispute", "title": "Refund", "channel": "whatsapp"},
        "locale": "en-IN",
    }


@pytest.fixture
def make_session(client, keys):
    def _make(tenant: str, task: str, user: str = "eu_1") -> str:
        r = client.post("/v1/sessions", json=session_body(tenant, task, user), headers=headers(keys[tenant]))
        assert r.status_code in (200, 201), r.text
        return r.json()["session_id"]
    return _make
