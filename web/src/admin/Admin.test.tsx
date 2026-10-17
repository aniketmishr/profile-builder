import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Admin } from "./Admin";
import { Viewer } from "./Viewer";
import { adminApi } from "../api";

const session = (created: boolean) => ({
  session_id: "ss_77", status: "created", created, chat_url: "http://localhost/chat/ss_77?token=t0k",
  tenant_id: "tn_acme", agent_id: "ag_104", end_user_id: "eu_55021", task_id: "task_8f3a21",
});

function route(handlers: Record<string, (init: RequestInit) => { status?: number; body: unknown }>) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const h = handlers[`${init.method ?? "GET"} ${url}`];
    if (!h) throw new Error(`unexpected request ${init.method} ${url}`);
    const { status = 200, body } = h(init);
    return { ok: status < 400, status, json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("mock admin panel", () => {
  it("connects with an API key, then launches a debrief that opens the embedded chat", async () => {
    const fetch = route({
      "GET /v1/whoami": () => ({ body: { tenant_id: "tn_acme" } }),
      "POST /v1/sessions": () => ({ status: 201, body: session(true) }),
    });
    const user = userEvent.setup();
    render(<Admin />);
    await user.type(screen.getByLabelText("API key"), "pk_demo");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Tenant tn_acme")).toBeInTheDocument();

    const row = screen.getByText("Refund for damaged order #44871").closest("li")!;
    await user.click(within(row).getByRole("button", { name: "Debrief" }));
    expect(await screen.findByText("New session")).toBeInTheDocument();
    expect(screen.getByTitle("Debrief chat")).toHaveAttribute("src", "http://localhost/chat/ss_77?token=t0k");

    const created = JSON.parse((fetch.mock.calls.find((c) => c[0] === "/v1/sessions")![1] as RequestInit).body as string);
    expect(created).toMatchObject({ idempotency_key: "task_8f3a21", tenant_id: "tn_acme", end_user: { id: "eu_55021" }, task: { type: "refund_dispute" } });
    expect(created.task.transcript_excerpt).toContain("WhatsApp");
  });

  it("says when an existing session was resumed, and 'fresh' makes a new idempotency key", async () => {
    route({
      "GET /v1/whoami": () => ({ body: { tenant_id: "tn_acme" } }),
      "POST /v1/sessions": () => ({ body: session(false) }),
    });
    sessionStorage.setItem("pb_api_key", "pk_demo");
    const user = userEvent.setup();
    render(<Admin />);
    expect(await screen.findByText("Tenant tn_acme")).toBeInTheDocument(); // reconnects from the stored key
    await user.click(within(screen.getByText("Refund for damaged order #44871").closest("li")!).getByRole("button", { name: "Debrief" }));
    expect(await screen.findByText("Resumed existing session")).toBeInTheDocument();

    await user.click(screen.getByLabelText(/fresh session/));
    await user.click(within(screen.getByText("Refund for damaged order #44871").closest("li")!).getByRole("button", { name: "Debrief" }));
    await waitFor(() => {
      const bodies = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter((c) => c[0] === "/v1/sessions").map((c) => JSON.parse(c[1].body).idempotency_key);
      expect(bodies[0]).toBe("task_8f3a21");
      expect(bodies[1]).toMatch(/^task_8f3a21-\d+$/);
    });
  });

  it("shows a clear error for a bad key and stays on the connect screen", async () => {
    route({ "GET /v1/whoami": () => ({ status: 401, body: { detail: "Invalid or revoked API key" } }) });
    const user = userEvent.setup();
    render(<Admin />);
    await user.type(screen.getByLabelText("API key"), "nope");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or revoked API key");
    expect(screen.getByLabelText("API key")).toBeInTheDocument();
  });

  it("shows a toast when the embedded chat reports the profile was saved", async () => {
    route({
      "GET /v1/whoami": () => ({ body: { tenant_id: "tn_acme" } }),
      "POST /v1/sessions": () => ({ status: 201, body: session(true) }),
    });
    sessionStorage.setItem("pb_api_key", "pk_demo");
    const user = userEvent.setup();
    render(<Admin />);
    await screen.findByText("Tenant tn_acme");
    await user.click(within(screen.getByText("Refund for damaged order #44871").closest("li")!).getByRole("button", { name: "Debrief" }));
    await screen.findByText("New session");
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { origin: window.location.origin, data: { type: "profile-builder:saved", saved: 3, discarded: 1 } }));
    });
    expect(await screen.findByRole("status")).toHaveTextContent("3 fact(s) saved, 1 discarded");
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { origin: "https://evil.example", data: { type: "profile-builder:saved", saved: 99 } }));
    });
    expect(screen.getByRole("status")).not.toHaveTextContent("99"); // messages from other origins are ignored
  });
});

describe("profile viewer", () => {
  const fact = (over: object) => ({ id: "f1", category: "contact_preferences", key: "preferred_channel", value: "whatsapp", confidence: 0.95, evidence: "only whatsapp", source_session_id: "ss_1", captured_at: "2026-10-16T09:00:00Z", is_current: true, superseded_by: null, provenance: { agent_edited: true }, ...over });

  it("lists current facts with confidence, evidence and source, plus history and the context block", async () => {
    route({
      "GET /v1/profiles/eu_55021": () => ({ body: { end_user_id: "eu_55021", tenant_id: "tn_acme", display_name: "Rahul M.", profile_version: 3, updated_at: "2026-10-16T09:00:00Z", facts: [fact({})] } }),
      "GET /v1/profiles/eu_55021/history": () => ({ body: { end_user_id: "eu_55021", sessions: [{ session_id: "ss_1", task_id: "task_8f3a21", task_type: "refund_dispute", task_title: "Refund for damaged order", agent_id: "ag_104", created_at: null }], history: [{ category: "contact_preferences", key: "preferred_channel", versions: [fact({ id: "f0", value: "email", is_current: false }), fact({})] }] } }),
      "GET /v1/profiles/eu_55021/context?max_tokens=300": () => ({ body: { context: "Rahul M. (eu_55021): Contact: preferred channel whatsapp.", approx_tokens: 12, truncated: false } }),
    });
    render(<Viewer api={adminApi("k")} initialUser="eu_55021" />);
    expect(await screen.findByText("Rahul M.")).toBeInTheDocument();
    expect(screen.getByText("Version 3", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText("whatsapp").length).toBeGreaterThan(0);
    expect(screen.getByText("edited by agent")).toBeInTheDocument();
    expect(screen.getByText("“only whatsapp”")).toBeInTheDocument();
    expect(screen.getAllByText(/Refund for damaged order \(task_8f3a21\)/).length).toBeGreaterThan(0);
    expect(screen.getByText("(2 versions)")).toBeInTheDocument();
    expect(screen.getByText("superseded")).toBeInTheDocument();
    expect(screen.getByText(/Contact: preferred channel whatsapp\./)).toBeInTheDocument();
  });

  it("says so when the end user has no profile", async () => {
    route({
      "GET /v1/profiles/eu_none": () => ({ status: 404, body: { detail: "end user not found" } }),
      "GET /v1/profiles/eu_none/history": () => ({ status: 404, body: { detail: "end user not found" } }),
      "GET /v1/profiles/eu_none/context?max_tokens=300": () => ({ status: 404, body: { detail: "end user not found" } }),
    });
    render(<Viewer api={adminApi("k")} initialUser="eu_none" />);
    expect(await screen.findByText("No profile for that end user yet.")).toBeInTheDocument();
  });
});
