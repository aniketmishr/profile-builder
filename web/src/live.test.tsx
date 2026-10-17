// Optional end-to-end test: the real Chat component against a REAL running server (no mocks).
//   LIVE_API=http://localhost:8000 LIVE_API_KEY=pk_... npm run test:live
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { adminApi, chatApi } from "./api";
import { Chat } from "./chat/Chat";
import { installFakeMedia } from "./chat/fakeMedia";

const BASE = process.env.LIVE_API;
const KEY = process.env.LIVE_API_KEY;

describe.skipIf(!BASE || !KEY)("live: debrief chat against a real server", () => {
  beforeAll(() => {
    const real = globalThis.fetch;
    // Test-environment shim only: jsdom's Blob is not understood by Node's fetch (browsers have no such gap).
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      const body = init?.body instanceof Blob ? await init.body.arrayBuffer() : init?.body;
      return real(`${BASE}${url}`, { ...init, body });
    });
  });
  afterAll(() => vi.unstubAllGlobals());

  it("answers every question, reviews, saves, and the facts reach the profile", async () => {
    const admin = adminApi(KEY!);
    const { tenant_id } = await admin.whoami();
    const stamp = Date.now();
    const userId = `eu_live_${stamp}`;
    const session = await admin.createSession({
      idempotency_key: `task_live_${stamp}`, tenant_id,
      agent: { id: "ag_live", name: "Live Agent" }, end_user: { id: userId, display_name: "Live User" },
      task: { id: `task_live_${stamp}`, type: "refund_dispute", title: "Live test refund" },
    });
    const token = session.chat_url.split("token=")[1];

    render(<Chat sessionId={session.session_id} api={chatApi(token)} pollMs={300} />);
    const user = userEvent.setup();
    const box = () => screen.queryByLabelText("Your answer");
    const reviewing = () => screen.queryAllByLabelText(/^Value for/).length > 0 || screen.queryByText("Nothing to save from this debrief.");

    for (let i = 0; i < 10; i++) {
      await waitFor(() => {
        const b = box();
        if (b) expect(b).toBeEnabled();
        else expect(reviewing()).toBeTruthy();
      }, { timeout: 20000 });
      const b = box();
      if (!b) break;
      await user.type(b, `answer number ${i + 1} about the customer{Enter}`);
    }

    await user.click(await screen.findByRole("button", { name: /^Save \d+ facts?$/ }, { timeout: 20000 }));
    expect(await screen.findByText("Saved ✓", {}, { timeout: 20000 })).toBeInTheDocument();

    const profile = await admin.profile(userId);
    expect(profile.facts.length).toBeGreaterThan(0);
    expect(profile.facts.every((f) => f.provenance?.origin === "extraction")).toBe(true);
  }, 120000);

  // Needs the server started with STT_PROVIDER=dev (a stub transcriber). Only the microphone is simulated.
  it.skipIf(!process.env.LIVE_VOICE)("records a voice answer, edits the transcript, and sends it", async () => {
    installFakeMedia();
    const admin = adminApi(KEY!);
    const { tenant_id } = await admin.whoami();
    const stamp = Date.now();
    const session = await admin.createSession({
      idempotency_key: `task_voice_${stamp}`, tenant_id,
      agent: { id: "ag_live", name: "Live Agent" }, end_user: { id: `eu_voice_${stamp}`, display_name: "Voice User" },
      task: { id: `task_voice_${stamp}`, type: "refund_dispute", title: "Live voice test" },
    });
    const token = session.chat_url.split("token=")[1];
    render(<Chat sessionId={session.session_id} api={chatApi(token)} pollMs={300} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Record a voice note" }, { timeout: 20000 }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    const box = screen.getByLabelText("Your answer") as HTMLTextAreaElement;
    await waitFor(() => {
      expect(box).toBeEnabled();
      expect(box.value).toContain("stub transcript");
    }, { timeout: 20000 });
    expect(screen.getByText(/Transcribed from your voice note/)).toBeInTheDocument();

    await user.clear(box);
    await user.type(box, "he wants WhatsApp only");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(async () => {
      const state = await chatApi(token).getDebrief(session.session_id);
      expect(state.messages.find((m) => m.role === "agent")?.text).toBe("he wants WhatsApp only");
      expect(state.progress.asked).toBeGreaterThan(1); // and the debrief moved on to the next question
    }, { timeout: 20000 });
  }, 60000);
});
