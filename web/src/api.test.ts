import { afterEach, describe, expect, it, vi } from "vitest";
import { adminApi, ApiError, chatApi } from "./api";
import { readChatLocation } from "./embed";
import { buildDecisions, textToValue } from "./chat/decisions";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client", () => {
  it("chat calls carry only the session token", async () => {
    const fetch = stubFetch(200, { ok: 1 });
    await chatApi("tok123").getDebrief("ss_1");
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/v1/sessions/ss_1/debrief");
    expect(init.headers).toEqual({ "X-Session-Token": "tok123" });
    expect(JSON.stringify(init.headers)).not.toContain("X-API-Key");
  });

  it("admin calls carry the API key and send JSON bodies", async () => {
    const fetch = stubFetch(201, { session_id: "ss_1" });
    await adminApi("pk_k").createSession({ idempotency_key: "k", tenant_id: "t", agent: { id: "a", name: "A" }, end_user: { id: "u", display_name: "U" }, task: { id: "t1", type: "x" } });
    const [, init] = fetch.mock.calls[0];
    expect(init.headers).toEqual({ "X-API-Key": "pk_k", "Content-Type": "application/json" });
    expect(JSON.parse(init.body).idempotency_key).toBe("k");
  });

  it("turns FastAPI errors into readable messages", async () => {
    stubFetch(409, { detail: "debrief already complete" });
    await expect(chatApi("t").getDebrief("s")).rejects.toMatchObject({ status: 409, message: "debrief already complete" });
    stubFetch(422, { detail: [{ msg: "field required" }, { msg: "too short" }] });
    await expect(chatApi("t").getDebrief("s")).rejects.toThrow("field required; too short");
  });

  it("reports an unreachable server with status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    await expect(chatApi("t").getDebrief("s")).rejects.toBeInstanceOf(ApiError);
    await expect(chatApi("t").getDebrief("s")).rejects.toMatchObject({ status: 0 });
  });

  it("encodes ids in paths", async () => {
    const fetch = stubFetch(200, {});
    await adminApi("k").profile("eu 1/2");
    expect(fetch.mock.calls[0][0]).toBe("/v1/profiles/eu%201%2F2");
  });
});

describe("chat link handling", () => {
  const history = () => ({ replaceState: vi.fn() }) as unknown as History;
  const loc = (path: string, search = "") => ({ pathname: path, search }) as Location;

  it("takes the token from the URL, stores it, and removes it from the address bar", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) } as Storage;
    const h = history();
    expect(readChatLocation(loc("/chat/ss_9", "?token=abc"), storage, h)).toEqual({ sessionId: "ss_9", token: "abc" });
    expect(h.replaceState).toHaveBeenCalledWith(null, "", "/chat/ss_9");
    // a reload no longer has the token in the URL, but the tab remembers it
    expect(readChatLocation(loc("/chat/ss_9"), storage, history())).toEqual({ sessionId: "ss_9", token: "abc" });
  });

  it("returns a null token when there is none, and null for other paths", () => {
    const storage = { getItem: () => null, setItem: () => {} } as unknown as Storage;
    expect(readChatLocation(loc("/chat/ss_1"), storage, history())).toEqual({ sessionId: "ss_1", token: null });
    expect(readChatLocation(loc("/admin"), storage, history())).toBeNull();
  });
});

describe("decisions", () => {
  const f = (id: string, value: string | string[]) => ({ id, category: "c", key: "k", value, confidence: 1, evidence: "e", status: "proposed" as const, edited: false });
  it("sends nothing when nothing changed", () => {
    expect(buildDecisions([f("a", "x")], { texts: { a: "x" }, discarded: new Set() })).toEqual([]);
  });
  it("ignores surrounding whitespace and list formatting", () => {
    expect(buildDecisions([f("a", "x"), f("b", ["p", "q"])], { texts: { a: " x ", b: "p,  q" }, discarded: new Set() })).toEqual([]);
    expect(textToValue("p, , q,", ["x"])).toEqual(["p", "q"]);
  });
  it("a discarded fact is discarded even if it was edited", () => {
    expect(buildDecisions([f("a", "x")], { texts: { a: "changed" }, discarded: new Set(["a"]) })).toEqual([{ fact_id: "a", action: "discard" }]);
  });
});
