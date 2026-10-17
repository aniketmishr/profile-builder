# 0012 Web UI: one React app, served by the API, embeddable by iframe
Status: accepted (slice 4)

**Context.** The brief wants an embeddable debrief chat (iframe or web component taking a session token), a mock
admin panel that lists tasks and launches it, and a small profile viewer. React (Vite) is preferred. The chat must
never hold a tenant API key, and the whole thing should stay one deployable service.

**Decision.**
- One Vite + React + TypeScript app in `web/`, built to static files that the API serves (`app/web.py`):
  `/chat/<session>` (the embeddable chat), `/admin` (mock admin panel with the profile viewer as a tab).
  The Docker image builds it in a Node stage; locally `npm run build:api` copies it to `app/static`.
  No router library: the three entry points are told apart by path.
- The chat talks to the API with the session token only (`X-Session-Token`, ADR 0009). On load the token is moved
  from the URL to `sessionStorage` and removed from the address bar (history, screenshots), so a reload still works.
  The page is served `Cache-Control: no-store`. The access log records paths only, never query strings.
- Embedding: the chat page sends `Content-Security-Policy: frame-ancestors $FRAME_ANCESTORS` (default `*` for the
  demo; set it to the admin panel's origin in production). Every other page may only be framed by this site.
  The chat tells the host page when facts are saved with `postMessage`, targeting the origin taken from the
  referrer (never `*`); the mock panel ignores messages from any other origin.
- The mock admin panel takes the API key by paste and calls the API from the browser. That is a demo shortcut: a real
  panel creates sessions on its server. The key lives in `sessionStorage` and is never sent to the chat iframe.
  Launching the same task twice resumes the same session (idempotency key = task id); a checkbox forces a fresh one.
- API types in `web/src/types.ts` mirror `app/schemas.py` by hand (no codegen at this size).
- The agent's edits are computed on the client but only changes are sent (`buildDecisions`); the server keeps
  everything not mentioned (ADR 0011). Pure logic (decisions, token handling) lives outside components so it is unit-tested.

**Alternatives.** Next.js (a second server). A web component (more plumbing for the same embedding). Vanilla JS with
no build (simpler, but not the preferred stack and harder to test). Server-side demo endpoint holding the key
(safer demo, but needs a demo login and more secrets).

**Consequences.** Testing is layered: component tests with a mocked API (36), plus an optional end-to-end test that
runs the real chat component against a real server (`npm run test:live`). Nothing here has been looked at in a real
browser, so layout and styling are unverified. `frame-ancestors *` must be tightened before real use. Voice recording
will extend the composer in the next slice. The token is a bearer credential for its TTL, visible to anything in the
page.
