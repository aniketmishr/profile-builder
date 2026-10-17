// Optional end-to-end test: the real Chat component against a REAL running server (no mocks).
//   LIVE_API=http://localhost:8000 LIVE_API_KEY=pk_... npm run test:live
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { adminApi, chatApi } from "./api";
import { Chat } from "./chat/Chat";

const BASE = process.env.LIVE_API;
const KEY = process.env.LIVE_API_KEY;

describe.skipIf(!BASE || !KEY)("live: debrief chat against a real server", () => {
  beforeAll(() => {
    const real = globalThis.fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => real(`${BASE}${url}`, init));
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
});
