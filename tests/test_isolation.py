"""Tenant A and tenant B must never see or touch each other's data, through any endpoint."""
from tests.conftest import headers
from tests.test_profiles import fact


def test_tenant_b_cannot_read_or_write_tenant_a(client, keys, make_session):
    a_session = make_session("tn_a", "task_iso_a", user="eu_secret")
    client.post(
        "/v1/profiles/eu_secret/facts",
        json={"source_session_id": a_session, "facts": [fact("preferred_channel", "whatsapp")]},
        headers=headers(keys["tn_a"]),
    )
    b = headers(keys["tn_b"])

    # reads: the end user does not exist in tenant B, so every read is a 404
    assert client.get("/v1/profiles/eu_secret", headers=b).status_code == 404
    assert client.get("/v1/profiles/eu_secret/history", headers=b).status_code == 404
    assert client.get("/v1/profiles/eu_secret/context", headers=b).status_code == 404
    assert client.get(f"/v1/sessions/{a_session}", headers=b).status_code == 404

    # write into A's end user with A's session: 404
    r = client.post("/v1/profiles/eu_secret/facts", headers=b,
                    json={"source_session_id": a_session, "facts": [fact("preferred_channel", "email")]})
    assert r.status_code == 404

    # write into B's own end user but cite A's session: 404, not accepted
    r = client.post("/v1/profiles/eu_1/facts", headers=b,
                    json={"source_session_id": a_session, "facts": [fact("preferred_channel", "email")]})
    assert r.status_code == 404

    # A's data is untouched
    a_profile = client.get("/v1/profiles/eu_secret", headers=headers(keys["tn_a"])).json()
    assert [f["value"] for f in a_profile["facts"]] == ["whatsapp"]


def test_same_end_user_id_in_two_tenants_never_mixes(client, keys, make_session):
    sa = make_session("tn_a", "task_mix_a")
    sb = make_session("tn_b", "task_mix_b")
    for tenant, sid, value in (("tn_a", sa, "whatsapp"), ("tn_b", sb, "sms")):
        client.post("/v1/profiles/eu_1/facts", headers=headers(keys[tenant]),
                    json={"source_session_id": sid, "facts": [fact("mix_channel", value)]})
    for tenant, value in (("tn_a", "whatsapp"), ("tn_b", "sms")):
        facts = client.get("/v1/profiles/eu_1", headers=headers(keys[tenant])).json()["facts"]
        assert [f["value"] for f in facts if f["key"] == "mix_channel"] == [value]


def test_revoked_key_stops_working(client, keys):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db import _sessionmaker
    from app.models import ApiKey
    from app.security import generate_api_key, hash_key
    from app.ids import new_id

    full, prefix, h = generate_api_key()
    db = _sessionmaker()()
    db.add(ApiKey(id=new_id("ak"), tenant_id="tn_a", prefix=prefix, key_hash=h))
    db.commit()
    assert client.get("/v1/profiles/eu_1", headers=headers(full)).status_code == 200
    row = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalar_one()
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.close()
    assert client.get("/v1/profiles/eu_1", headers=headers(full)).status_code == 401
