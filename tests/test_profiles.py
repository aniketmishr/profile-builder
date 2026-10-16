from tests.conftest import headers


def fact(key="preferred_channel", value="whatsapp", conf=0.9, cat="contact_preferences", ev="only whatsapp"):
    return {"category": cat, "key": key, "value": value, "confidence": conf, "evidence": ev}


def write(client, keys, sid, facts, user="eu_1", tenant="tn_a"):
    return client.post(
        f"/v1/profiles/{user}/facts",
        json={"source_session_id": sid, "facts": facts},
        headers=headers(keys[tenant]),
    )


def test_write_then_read_back(client, keys, make_session):
    sid = make_session("tn_a", "task_p1")
    r = write(client, keys, sid, [fact(), fact("refund_preference", "store_credit", cat="constraints")])
    assert r.status_code == 200 and len(r.json()["written"]) == 2
    p = client.get("/v1/profiles/eu_1", headers=headers(keys["tn_a"])).json()
    got = {(f["category"], f["key"]): f["value"] for f in p["facts"]}
    assert got[("contact_preferences", "preferred_channel")] == "whatsapp"
    assert got[("constraints", "refund_preference")] == "store_credit"
    assert p["profile_version"] >= 1 and p["tenant_id"] == "tn_a"
    assert all(f["provenance"] == {"origin": "manual"} for f in p["facts"])


def test_new_value_supersedes_and_history_is_kept(client, keys, make_session):
    s1 = make_session("tn_a", "task_s1")
    s2 = make_session("tn_a", "task_s2")
    write(client, keys, s1, [fact("tz_pref", "IST", cat="personal_context")])
    r = write(client, keys, s2, [fact("tz_pref", "PST", cat="personal_context")])
    assert r.status_code == 200
    h = client.get("/v1/profiles/eu_1/history", headers=headers(keys["tn_a"])).json()
    versions = next(x for x in h["history"] if x["key"] == "tz_pref")["versions"]
    assert [v["value"] for v in versions] == ["IST", "PST"]
    assert [v["is_current"] for v in versions] == [False, True]
    assert versions[0]["superseded_by"] == versions[1]["id"]
    assert {s["session_id"] for s in h["sessions"]} >= {s1, s2}
    current = client.get("/v1/profiles/eu_1", headers=headers(keys["tn_a"])).json()["facts"]
    assert [f["value"] for f in current if f["key"] == "tz_pref"] == ["PST"]


def test_same_value_is_a_noop(client, keys, make_session):
    sid = make_session("tn_a", "task_noop")
    write(client, keys, sid, [fact("lang", "hindi", cat="communication_style")])
    r = write(client, keys, sid, [fact("lang", "hindi", cat="communication_style")]).json()
    assert r["written"] == [] and len(r["unchanged"]) == 1


def test_duplicate_keys_in_one_batch_keep_highest_confidence(client, keys, make_session):
    sid = make_session("tn_a", "task_dup")
    r = write(client, keys, sid, [fact("budget", "low", 0.4, "constraints"), fact("budget", "tight", 0.8, "constraints")]).json()
    assert len(r["written"]) == 1 and r["written"][0]["value"] == "tight"


def test_source_session_must_belong_to_that_end_user(client, keys, make_session):
    sid = make_session("tn_a", "task_other_user", user="eu_2")
    assert write(client, keys, sid, [fact()], user="eu_1").status_code == 422


def test_invalid_fact_is_rejected(client, keys, make_session):
    sid = make_session("tn_a", "task_bad")
    bad = fact()
    bad["confidence"] = 1.5
    assert write(client, keys, sid, [bad]).status_code == 422
    bad = fact()
    bad["category"] = "made_up"
    assert write(client, keys, sid, [bad]).status_code == 422


def test_context_block_and_budget(client, keys, make_session):
    sid = make_session("tn_a", "task_ctx", user="eu_ctx")
    write(client, keys, sid, [
        fact("preferred_channel", "whatsapp"),
        fact("avoid_channel", "email"),
        fact("refund_preference", "store_credit", cat="constraints"),
        fact("notes_1", "likes short replies " * 8, cat="notes"),
    ], user="eu_ctx")
    full = client.get("/v1/profiles/eu_ctx/context", headers=headers(keys["tn_a"])).json()
    assert "preferred channel whatsapp" in full["context"] and full["truncated"] is False
    small = client.get("/v1/profiles/eu_ctx/context?max_tokens=40", headers=headers(keys["tn_a"])).json()
    assert small["truncated"] is True and small["approx_tokens"] <= 40
    assert "whatsapp" in small["context"]  # highest-priority facts survive trimming
    txt = client.get("/v1/profiles/eu_ctx/context?format=text", headers=headers(keys["tn_a"]))
    assert txt.headers["content-type"].startswith("text/plain")


def test_profile_for_user_without_facts_is_empty_not_404(client, keys):
    r = client.get("/v1/profiles/eu_1", headers=headers(keys["tn_b"]))
    assert r.status_code == 200


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "db": "ok"}
