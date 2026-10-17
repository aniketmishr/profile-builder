from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import mount_web
from tests.conftest import headers


def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    (tmp_path / "index.html").write_text("<html><div id=root></div></html>")
    app = FastAPI()
    mount_web(app, tmp_path, "https://panel.example")
    return TestClient(app)


def test_chat_page_is_embeddable_only_by_the_configured_origin(tmp_path):
    r = built(tmp_path).get("/chat/ss_123?token=abc")
    assert r.status_code == 200 and "root" in r.text
    assert r.headers["content-security-policy"] == "frame-ancestors https://panel.example"
    assert "x-frame-options" not in r.headers
    assert r.headers["cache-control"] == "no-store"  # the page URL carries a token: never cache it


def test_admin_page_cannot_be_framed_by_other_sites(tmp_path):
    c = built(tmp_path)
    for path in ("/admin", "/admin/"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["content-security-policy"] == "frame-ancestors 'self'"


def test_assets_are_served_and_traversal_is_blocked(tmp_path):
    c = built(tmp_path)
    assert c.get("/assets/app.js").text == "console.log('hi')"
    assert c.get("/assets/%2e%2e/index.html").status_code in (400, 404)
    assert c.get("/assets/missing.js").status_code == 404


def test_unbuilt_app_gives_a_hint_instead_of_crashing(tmp_path):
    app = FastAPI()
    mount_web(app, tmp_path / "nope", "*")
    c = TestClient(app)
    for path in ("/chat/ss_1", "/admin"):
        r = c.get(path)
        assert r.status_code == 404 and "npm run build:api" in r.json()["detail"]


def test_whoami_returns_the_keys_tenant(client, keys):
    assert client.get("/v1/whoami", headers=headers(keys["tn_a"])).json() == {"tenant_id": "tn_a"}
    assert client.get("/v1/whoami", headers=headers(keys["tn_b"])).json() == {"tenant_id": "tn_b"}


def test_whoami_needs_an_api_key_not_a_session_token(client, keys, make_session):
    assert client.get("/v1/whoami").status_code == 401
    sid = make_session("tn_a", "task_whoami")
    token = client.get(f"/v1/sessions/{sid}", headers=headers(keys["tn_a"])).json()["chat_url"].split("token=")[1]
    assert client.get("/v1/whoami", headers={"X-Session-Token": token}).status_code == 401
