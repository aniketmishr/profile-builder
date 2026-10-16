from app.security import verify_session_token
from tests.conftest import headers, session_body


def test_requires_api_key(client):
    assert client.post("/v1/sessions", json=session_body("tn_a")).status_code == 401
    r = client.post("/v1/sessions", json=session_body("tn_a"), headers=headers("pk_bad_key"))
    assert r.status_code == 401


def test_create_then_duplicate_is_idempotent(client, keys):
    body = session_body("tn_a", task="task_idem")
    first = client.post("/v1/sessions", json=body, headers=headers(keys["tn_a"]))
    second = client.post("/v1/sessions", json=body, headers=headers(keys["tn_a"]))
    assert first.status_code == 201 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert first.json()["session_id"] == second.json()["session_id"]


def test_chat_url_carries_valid_signed_token(client, keys):
    r = client.post("/v1/sessions", json=session_body("tn_a", task="task_tok"), headers=headers(keys["tn_a"]))
    data = r.json()
    token = data["chat_url"].split("token=")[1]
    claims = verify_session_token(token)
    assert claims == {"sid": data["session_id"], "tid": "tn_a"}
    assert verify_session_token(token + "x") is None


def test_same_key_different_task_is_409(client, keys):
    client.post("/v1/sessions", json=session_body("tn_a", task="task_c1", key="shared"), headers=headers(keys["tn_a"]))
    r = client.post("/v1/sessions", json=session_body("tn_a", task="task_c2", key="shared"), headers=headers(keys["tn_a"]))
    assert r.status_code == 409


def test_body_tenant_must_match_key_tenant(client, keys):
    r = client.post("/v1/sessions", json=session_body("tn_b", task="task_x"), headers=headers(keys["tn_a"]))
    assert r.status_code == 403


def test_insert_race_falls_back_to_existing(client, keys, monkeypatch):
    """Simulate two concurrent calls: the pre-check misses, the unique constraint catches the loser."""
    from app.repo import ScopedRepo
    body = session_body("tn_a", task="task_race")
    winner = client.post("/v1/sessions", json=body, headers=headers(keys["tn_a"])).json()["session_id"]

    real = ScopedRepo.get_session_by_key
    calls = {"n": 0}

    def flaky(self, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(self, key)

    monkeypatch.setattr(ScopedRepo, "get_session_by_key", flaky)
    r = client.post("/v1/sessions", json=body, headers=headers(keys["tn_a"]))
    assert r.status_code == 200 and r.json()["session_id"] == winner


def test_get_session(client, keys):
    sid = client.post("/v1/sessions", json=session_body("tn_a", task="task_get"), headers=headers(keys["tn_a"])).json()["session_id"]
    assert client.get(f"/v1/sessions/{sid}", headers=headers(keys["tn_a"])).status_code == 200
    assert client.get("/v1/sessions/ss_nope", headers=headers(keys["tn_a"])).status_code == 404
