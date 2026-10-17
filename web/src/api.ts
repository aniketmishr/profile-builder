import type {
  AnswerBody, ConfirmResult, ContextOut, DebriefState, Decision, Extraction, History, Profile,
  SessionCreateBody, SessionOut, VoiceNote,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Auth = { token: string } | { key: string };

function authHeaders(auth: Auth): Record<string, string> {
  return "token" in auth ? { "X-Session-Token": auth.token } : { "X-API-Key": auth.key };
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? "invalid input").join("; ");
  return fallback;
}

/** `body` is sent as JSON; `blob` (a recording) is sent as-is with its own content type. */
async function call<T>(auth: Auth, method: string, path: string, body?: unknown, blob?: Blob): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: {
        ...authHeaders(auth),
        ...(blob ? { "Content-Type": blob.type || "application/octet-stream" } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: blob ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, `Request failed (${res.status})`));
  return data as T;
}

/** Everything the embedded chat needs. It only ever holds the session token, never the tenant API key. */
export function chatApi(token: string) {
  const auth = { token };
  const s = (id: string) => `/v1/sessions/${encodeURIComponent(id)}`;
  return {
    startDebrief: (id: string) => call<DebriefState>(auth, "POST", `${s(id)}/debrief/start`),
    getDebrief: (id: string) => call<DebriefState>(auth, "GET", `${s(id)}/debrief`),
    answer: (id: string, body: AnswerBody) => call<DebriefState>(auth, "POST", `${s(id)}/debrief/answer`, body),
    getExtraction: (id: string) => call<Extraction>(auth, "GET", `${s(id)}/extraction`),
    startExtraction: (id: string) => call<Extraction>(auth, "POST", `${s(id)}/extraction`),
    uploadVoice: (id: string, questionId: string, blob: Blob, durationMs: number) =>
      call<VoiceNote>(auth, "POST", `${s(id)}/voice?question_id=${encodeURIComponent(questionId)}&duration_ms=${Math.round(durationMs)}`, undefined, blob),
    getVoiceNote: (id: string, noteId: string) => call<VoiceNote>(auth, "GET", `${s(id)}/voice/${encodeURIComponent(noteId)}`),
    retryVoiceNote: (id: string, noteId: string) => call<VoiceNote>(auth, "POST", `${s(id)}/voice/${encodeURIComponent(noteId)}/retry`),
    confirm: (id: string, decisions: Decision[]) =>
      call<ConfirmResult>(auth, "POST", `${s(id)}/extraction/confirm`, { decisions }),
  };
}
export type ChatApi = ReturnType<typeof chatApi>;

/** Used by the mock admin panel and profile viewer (tenant API key). */
export function adminApi(key: string) {
  const auth = { key };
  const p = (id: string) => `/v1/profiles/${encodeURIComponent(id)}`;
  return {
    whoami: () => call<{ tenant_id: string }>(auth, "GET", "/v1/whoami"),
    createSession: (body: SessionCreateBody) => call<SessionOut>(auth, "POST", "/v1/sessions", body),
    profile: (id: string) => call<Profile>(auth, "GET", p(id)),
    history: (id: string) => call<History>(auth, "GET", `${p(id)}/history`),
    context: (id: string, maxTokens = 300) => call<ContextOut>(auth, "GET", `${p(id)}/context?max_tokens=${maxTokens}`),
  };
}
export type AdminApi = ReturnType<typeof adminApi>;
