# 0009 Session token for the embedded chat endpoints
Status: accepted (slice 2)

**Context.** The chat runs in the browser inside a third-party admin panel. It must not hold the tenant API key.
The brief asks for a signed session token for the chat page and a static API key per tenant otherwise.

**Decision.** The three debrief endpoints (`start`, `get`, `answer`) accept either `X-API-Key` (admin panel
server-side) or `X-Session-Token` (the token inside `chat_url`). A token carries `sid` and `tid`, is signed and
expires (`SESSION_TOKEN_TTL_SECONDS`). The tenant comes from the signed claims, never from the client. A token only
works for its own session: another session id returns 404 and a bad or expired token returns 401. Only these
routes use the token dependency (`deps.get_debrief_repo`), so a token cannot read profiles or other sessions.

**Alternatives.** Put the API key in the page (leaks it). A separate token-exchange endpoint (extra round trip,
no benefit at this size). Cookies (cross-site iframe problems).

**Consequences.** Any new endpoint the chat UI needs must use `get_debrief_repo` and verify the session id.
Tokens are bearer credentials valid for the TTL; revocation is not implemented. The profile viewer will need its own scheme.

**Addendum (slice 3).** The token also reaches `GET/POST .../extraction` and `POST .../extraction/confirm` for its own
session, because the chat shows the summary and saves the agent's decisions. Through those it can write facts only for
that session's end user, only after the agent confirms, and only once. It still cannot read profiles or any other session.
