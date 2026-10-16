"""End-to-end check against a running server (local or hosted).

    BASE_URL=https://your-app.onrender.com API_KEY=pk_... python -m scripts.smoke

Needs ENABLE_DEBUG_ENDPOINTS=true on the server (it writes facts by hand).
"""
import os
import sys
import uuid

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
KEY = os.environ.get("API_KEY")
TENANT = os.environ.get("TENANT_ID", "tn_acme")
USER = os.environ.get("END_USER_ID", "eu_55021")

if not KEY:
    sys.exit("Set API_KEY (printed by scripts.seed)")

H = {"X-API-Key": KEY}
c = httpx.Client(base_url=BASE, headers=H, timeout=60)  # generous: free hosts cold-start


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        sys.exit(1)


r = c.get("/health")
step("health", r.status_code == 200, r.text)

task = f"task_{uuid.uuid4().hex[:8]}"
body = {
    "idempotency_key": task, "tenant_id": TENANT,
    "agent": {"id": "ag_104", "name": "Priya S."},
    "end_user": {"id": USER, "display_name": "Rahul M."},
    "task": {"id": task, "type": "refund_dispute", "title": "Refund for damaged order",
             "channel": "whatsapp", "transcript_excerpt": "just WhatsApp me"},
    "locale": "en-IN",
}
r1 = c.post("/v1/sessions", json=body)
step("create session", r1.status_code == 201, r1.json().get("session_id", r1.text))
r2 = c.post("/v1/sessions", json=body)
step("duplicate is idempotent", r2.status_code == 200 and r2.json()["session_id"] == r1.json()["session_id"])
sid = r1.json()["session_id"]
print("     chat_url:", r1.json()["chat_url"])

facts = [
    {"category": "contact_preferences", "key": "preferred_channel", "value": "whatsapp", "confidence": 0.95, "evidence": "only whatsapp"},
    {"category": "contact_preferences", "key": "avoid_channel", "value": "email", "confidence": 0.95, "evidence": "never email him"},
    {"category": "constraints", "key": "refund_preference", "value": "store_credit", "confidence": 0.9, "evidence": "store credit instead of refund"},
]
w = c.post(f"/v1/profiles/{USER}/facts", json={"source_session_id": sid, "facts": facts})
step("write facts", w.status_code == 200, f"profile_version={w.json().get('profile_version')}")

supersede = [{"category": "constraints", "key": "refund_preference", "value": "refund_to_card", "confidence": 0.8, "evidence": "changed his mind"}]
w2 = c.post(f"/v1/profiles/{USER}/facts", json={"source_session_id": sid, "facts": supersede})
step("supersede a fact", w2.status_code == 200 and len(w2.json()["written"]) == 1)

p = c.get(f"/v1/profiles/{USER}").json()
vals = {f["key"]: f["value"] for f in p["facts"]}
step("merged profile shows latest value", vals.get("refund_preference") == "refund_to_card", str(vals))

h = c.get(f"/v1/profiles/{USER}/history").json()
versions = next(x for x in h["history"] if x["key"] == "refund_preference")["versions"]
step("history keeps the old value", len(versions) >= 2, str([v["value"] for v in versions]))

ctx = c.get(f"/v1/profiles/{USER}/context", params={"max_tokens": 150}).json()
step("context block", "whatsapp" in ctx["context"], "\n     " + ctx["context"])
print("\nAll good.")
