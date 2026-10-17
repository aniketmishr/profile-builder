import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ChatApi } from "../api";
import type { ConfirmResult, DebriefState, Extraction, ExtractedFact } from "../types";
import { Chat } from "./Chat";
import { installFakeMedia, removeFakeMedia } from "./fakeMedia";

const msg = (seq: number, role: "ai" | "agent", text: string, extra: object = {}) =>
  ({ id: `m${seq}`, seq, role, text, question_id: null, action: null, created_at: null, ...extra });

function state(over: Partial<DebriefState> = {}): DebriefState {
  return {
    session_id: "ss_1", state: "active", end_reason: null, plan_source: "llm", current_question_id: "dq_1",
    progress: { asked: 1, cap: 7 }, voice_enabled: false, questions: [],
    messages: [msg(1, "ai", "Quick debrief on Rahul: refund. 3 short questions."), msg(2, "ai", "How should we contact Rahul?", { question_id: "dq_1" })],
    ...over,
  };
}

const fact = (id: string, key: string, value: string | string[], over: Partial<ExtractedFact> = {}): ExtractedFact =>
  ({ id, category: "contact_preferences", key, value, confidence: 0.9, evidence: "only whatsapp", status: "proposed", edited: false, ...over });

const extraction = (over: Partial<Extraction> = {}): Extraction => ({
  session_id: "ss_1", status: "ready", source: "llm", prompt_version: "extractor_v1", model: "m", error: null,
  attempt: 1, dropped_count: 0, facts: [fact("xf_1", "preferred_channel", "whatsapp"), fact("xf_2", "avoid_channel", "email")], ...over,
});

function fakeApi(over: Partial<Record<keyof ChatApi, unknown>> = {}) {
  const api = {
    startDebrief: vi.fn().mockResolvedValue(state()),
    getDebrief: vi.fn().mockResolvedValue(state()),
    answer: vi.fn(),
    getExtraction: vi.fn().mockResolvedValue(extraction()),
    startExtraction: vi.fn().mockResolvedValue(extraction({ status: "running", facts: [] })),
    confirm: vi.fn().mockResolvedValue({ saved: [], unchanged: [], discarded: 0, profile_version: 1 } satisfies ConfirmResult),
    uploadVoice: vi.fn(),
    getVoiceNote: vi.fn(),
    retryVoiceNote: vi.fn(),
    ...over,
  };
  return api as unknown as ChatApi & typeof api;
}

const complete = (): DebriefState => state({
  state: "complete", end_reason: "all_answered", current_question_id: null,
  messages: [...state().messages, msg(3, "agent", "only whatsapp", { action: "answer" }), msg(4, "ai", "That's everything I needed, thank you!")],
});

describe("debrief conversation", () => {
  it("starts the debrief on open and shows the first question and progress", async () => {
    const api = fakeApi();
    render(<Chat sessionId="ss_1" api={api} />);
    expect(await screen.findByText("How should we contact Rahul?")).toBeInTheDocument();
    expect(api.startDebrief).toHaveBeenCalledWith("ss_1");
    expect(screen.getByText(/Question 1 of up to 7/)).toBeInTheDocument();
  });

  it("sends the answer with the current question id, then shows the next question", async () => {
    const next = state({ current_question_id: "dq_2", progress: { asked: 2, cap: 7 }, messages: [
      ...state().messages, msg(3, "agent", "only whatsapp", { action: "answer" }), msg(4, "ai", "Anything that frustrated him?", { question_id: "dq_2" })] });
    const api = fakeApi({ answer: vi.fn().mockResolvedValue(next) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.type(await screen.findByLabelText("Your answer"), "only whatsapp");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.answer).toHaveBeenCalledWith("ss_1", { question_id: "dq_1", action: "answer", text: "only whatsapp" });
    expect(await screen.findByText("Anything that frustrated him?")).toBeInTheDocument();
    expect(screen.getByLabelText("Your answer")).toHaveValue("");
  });

  it("Enter sends, Shift+Enter does not", async () => {
    const api = fakeApi({ answer: vi.fn().mockResolvedValue(state()) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    const box = await screen.findByLabelText("Your answer");
    await user.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(api.answer).not.toHaveBeenCalled();
    await user.type(box, "{Enter}");
    expect(api.answer).toHaveBeenCalledWith("ss_1", expect.objectContaining({ text: "line one\nline two" }));
  });

  it("Send is disabled while the box is empty", async () => {
    render(<Chat sessionId="ss_1" api={fakeApi()} />);
    await screen.findByLabelText("Your answer");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("Skip sends a skip without text", async () => {
    const api = fakeApi({ answer: vi.fn().mockResolvedValue(state()) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    expect(api.answer).toHaveBeenCalledWith("ss_1", { question_id: "dq_1", action: "skip" });
  });

  it("ending needs a second click and can be cancelled", async () => {
    const api = fakeApi({ answer: vi.fn().mockResolvedValue(complete()) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.click(await screen.findByRole("button", { name: "End debrief" }));
    expect(api.answer).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Keep going" }));
    expect(screen.getByRole("button", { name: "End debrief" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "End debrief" }));
    await user.click(screen.getByRole("button", { name: "End now" }));
    expect(api.answer).toHaveBeenCalledWith("ss_1", { question_id: "dq_1", action: "end" });
  });

  it("a stale question (409) refreshes the state instead of failing", async () => {
    const latest = state({ current_question_id: "dq_2", messages: [...state().messages, msg(3, "ai", "Newer question?", { question_id: "dq_2" })] });
    const api = fakeApi({ answer: vi.fn().mockRejectedValue(new ApiError(409, "stale")), getDebrief: vi.fn().mockResolvedValue(latest) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.type(await screen.findByLabelText("Your answer"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Newer question?")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/already handled/);
  });

  it("keeps the typed text when sending fails, and reports the error", async () => {
    const api = fakeApi({ answer: vi.fn().mockRejectedValue(new ApiError(0, "Can't reach the server.")) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.type(await screen.findByLabelText("Your answer"), "important words");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server.");
    expect(screen.getByLabelText("Your answer")).toHaveValue("important words");
  });

  it("offers a retry when the debrief cannot be started", async () => {
    const startDebrief = vi.fn().mockRejectedValueOnce(new ApiError(0, "offline")).mockResolvedValue(state());
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={fakeApi({ startDebrief })} />);
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("How should we contact Rahul?")).toBeInTheDocument();
  });

  it("renders skipped answers as a quiet note, not an empty bubble", async () => {
    const s = state({ messages: [...state().messages, msg(3, "agent", "", { action: "skip" })] });
    render(<Chat sessionId="ss_1" api={fakeApi({ startDebrief: vi.fn().mockResolvedValue(s) })} />);
    expect(await screen.findByText("Skipped")).toBeInTheDocument();
  });
});

describe("summary, review and save", () => {
  const done = (api: ChatApi) => render(<Chat sessionId="ss_1" api={api} pollMs={5} />);

  it("waits for extraction, then shows the proposals with their evidence", async () => {
    const getExtraction = vi.fn()
      .mockResolvedValueOnce(extraction({ status: "running", facts: [] }))
      .mockResolvedValue(extraction());
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction }));
    expect(await screen.findByText("Preparing your summary…")).toBeInTheDocument();
    expect(await screen.findByLabelText("Value for preferred channel")).toHaveValue("whatsapp");
    expect(screen.getAllByText(/You said:/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Save 2 facts" })).toBeInTheDocument();
  });

  it("starts extraction itself when none exists yet", async () => {
    const getExtraction = vi.fn().mockRejectedValue(new ApiError(404, "extraction not started"));
    const startExtraction = vi.fn().mockResolvedValue(extraction());
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction, startExtraction }));
    expect(await screen.findByLabelText("Value for preferred channel")).toBeInTheDocument();
    expect(startExtraction).toHaveBeenCalledWith("ss_1");
  });

  it("sends only the changes: an edit and a discard; unchanged facts are kept by omission", async () => {
    const api = fakeApi({
      startDebrief: vi.fn().mockResolvedValue(complete()),
      getExtraction: vi.fn().mockResolvedValue(extraction({ facts: [
        fact("xf_1", "preferred_channel", "whatsapp"), fact("xf_2", "avoid_channel", "email"), fact("xf_3", "do_not_contact_after", "21:00 local")] })),
    });
    const user = userEvent.setup();
    done(api);
    const edit = await screen.findByLabelText("Value for do not contact after");
    await user.clear(edit);
    await user.type(edit, "21:30 local");
    await user.click(screen.getAllByRole("button", { name: "Discard" })[1]);
    await user.click(screen.getByRole("button", { name: "Save 2 facts" }));
    expect(api.confirm).toHaveBeenCalledWith("ss_1", [
      { fact_id: "xf_2", action: "discard" },
      { fact_id: "xf_3", action: "edit", value: "21:30 local" },
    ]);
  });

  it("refuses to save a kept fact whose value was emptied", async () => {
    const api = fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()) });
    const user = userEvent.setup();
    done(api);
    await user.clear(await screen.findByLabelText("Value for preferred channel"));
    await user.click(screen.getByRole("button", { name: "Save 2 facts" }));
    expect(await screen.findByText(/can't be empty/)).toBeInTheDocument();
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("keeps list values as lists when edited", async () => {
    const api = fakeApi({
      startDebrief: vi.fn().mockResolvedValue(complete()),
      getExtraction: vi.fn().mockResolvedValue(extraction({ facts: [fact("xf_1", "avoid_channel", ["email", "sms"])] })),
    });
    const user = userEvent.setup();
    done(api);
    const box = await screen.findByLabelText("Value for avoid channel");
    expect(box).toHaveValue("email, sms");
    await user.clear(box);
    await user.type(box, "email, sms, call");
    await user.click(screen.getByRole("button", { name: "Save 1 fact" }));
    expect(api.confirm).toHaveBeenCalledWith("ss_1", [{ fact_id: "xf_1", action: "edit", value: ["email", "sms", "call"] }]);
  });

  it("shows a saved screen after confirming", async () => {
    const confirmed = extraction({ status: "confirmed", facts: [fact("xf_1", "preferred_channel", "whatsapp", { status: "saved" }), fact("xf_2", "avoid_channel", "email", { status: "discarded" })] });
    const getExtraction = vi.fn().mockResolvedValueOnce(extraction()).mockResolvedValue(confirmed);
    const confirm = vi.fn().mockResolvedValue({ saved: [{}], unchanged: [], discarded: 1, profile_version: 2 });
    const user = userEvent.setup();
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction, confirm }));
    await user.click(await screen.findByRole("button", { name: "Save 2 facts" }));
    expect(await screen.findByText("Saved ✓")).toBeInTheDocument();
    expect(screen.getByText(/1 fact added/)).toBeInTheDocument();
    expect(screen.getByText("1 discarded.")).toBeInTheDocument();
  });

  it("resumes straight to the saved screen when it was already confirmed", async () => {
    const confirmed = extraction({ status: "confirmed", facts: [fact("xf_1", "preferred_channel", "whatsapp", { status: "saved" })] });
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction: vi.fn().mockResolvedValue(confirmed) }));
    expect(await screen.findByText("Saved ✓")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
  });

  it("explains the fallback and lets the agent retry a failed extraction", async () => {
    const getExtraction = vi.fn().mockResolvedValue(extraction({ status: "failed", facts: [] }));
    const startExtraction = vi.fn().mockResolvedValue(extraction({ source: "fallback" }));
    const user = userEvent.setup();
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction, startExtraction }));
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(startExtraction).toHaveBeenCalled());
  });

  it("shows the notes notice for fallback proposals", async () => {
    done(fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction: vi.fn().mockResolvedValue(extraction({ source: "fallback" })) }));
    expect(await screen.findByText(/saved as notes/)).toBeInTheDocument();
  });

  it("lets the agent finish when there is nothing to save", async () => {
    const api = fakeApi({ startDebrief: vi.fn().mockResolvedValue(complete()), getExtraction: vi.fn().mockResolvedValue(extraction({ facts: [], source: "none" })) });
    const user = userEvent.setup();
    done(api);
    expect(await screen.findByText("Nothing to save from this debrief.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish" }));
    expect(api.confirm).toHaveBeenCalledWith("ss_1", []);
  });
});

describe("voice answers in the chat", () => {
  const voiceState = (over: Partial<DebriefState> = {}) => state({ voice_enabled: true, ...over });
  const doneNote = { id: "vn_9", status: "done", question_id: "dq_1", transcript: "he wants whatsapp", error: null, attempt: 1, size_bytes: 7, duration_ms: 900 };

  async function record(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
  }

  beforeEach(() => { installFakeMedia(); });
  afterEach(() => removeFakeMedia());

  it("shows the microphone only when the server enabled voice", async () => {
    render(<Chat sessionId="ss_1" api={fakeApi()} />);
    await screen.findByLabelText("Your answer");
    expect(screen.queryByRole("button", { name: "Record a voice note" })).not.toBeInTheDocument();
  });

  it("hides the microphone when the browser cannot record, even if the server allows it", async () => {
    removeFakeMedia();
    render(<Chat sessionId="ss_1" api={fakeApi({ startDebrief: vi.fn().mockResolvedValue(voiceState()) })} />);
    await screen.findByLabelText("Your answer");
    expect(screen.queryByRole("button", { name: "Record a voice note" })).not.toBeInTheDocument();
  });

  it("puts the transcript in the box as an editable draft, and sends it with the voice note id", async () => {
    const api = fakeApi({
      startDebrief: vi.fn().mockResolvedValue(voiceState()),
      uploadVoice: vi.fn().mockResolvedValue({ ...doneNote, status: "queued", transcript: null }),
      getVoiceNote: vi.fn().mockResolvedValue(doneNote),
      answer: vi.fn().mockResolvedValue(state()),
    });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await record(user);
    const box = await screen.findByLabelText("Your answer");
    await waitFor(() => expect(box).toHaveValue("he wants whatsapp"));
    expect(screen.getByText(/Transcribed from your voice note/)).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, "he wants WhatsApp only");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.answer).toHaveBeenCalledWith("ss_1", {
      question_id: "dq_1", action: "answer", text: "he wants WhatsApp only", voice_note_id: "vn_9",
    });
  });

  it("locks the composer while recording or transcribing", async () => {
    const api = fakeApi({ startDebrief: vi.fn().mockResolvedValue(voiceState()) });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await user.click(await screen.findByRole("button", { name: "Record a voice note" }));
    await screen.findByRole("button", { name: "Stop" });
    expect(screen.getByLabelText("Your answer")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("does not attach a voice note to an answer for a different question", async () => {
    const q2 = voiceState({ current_question_id: "dq_2", messages: [...state().messages, msg(3, "ai", "Second?", { question_id: "dq_2" })] });
    const api = fakeApi({
      startDebrief: vi.fn().mockResolvedValue(voiceState()),
      uploadVoice: vi.fn().mockResolvedValue(doneNote),
      answer: vi.fn().mockResolvedValue(q2),
    });
    const user = userEvent.setup();
    render(<Chat sessionId="ss_1" api={api} />);
    await record(user);
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toHaveValue("he wants whatsapp"));
    await user.click(screen.getByRole("button", { name: "Skip" }));  // moves on to question 2
    await screen.findByText("Second?");
    await user.type(screen.getByLabelText("Your answer"), "typed answer");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.answer).toHaveBeenLastCalledWith("ss_1", { question_id: "dq_2", action: "answer", text: "typed answer" });
  });
});
