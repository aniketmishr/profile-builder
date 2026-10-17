import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ChatApi } from "../api";
import type { VoiceNote } from "../types";
import { FakeRecorder, installFakeMedia, removeFakeMedia } from "./fakeMedia";
import { VoiceInput } from "./VoiceInput";
import { formatClock, pickMimeType, voiceSupported } from "./voice";

const note = (status: VoiceNote["status"], over: Partial<VoiceNote> = {}): VoiceNote => ({
  id: "vn_1", status, question_id: "dq_1", transcript: null, error: null, attempt: 1, size_bytes: 7, duration_ms: 1000, ...over,
});

function setup(apiOver: Partial<Record<keyof ChatApi, unknown>> = {}, props: Partial<React.ComponentProps<typeof VoiceInput>> = {}) {
  const api = {
    uploadVoice: vi.fn().mockResolvedValue(note("queued")),
    getVoiceNote: vi.fn().mockResolvedValue(note("done", { transcript: "hello world" })),
    retryVoiceNote: vi.fn().mockResolvedValue(note("queued", { attempt: 2 })),
    ...apiOver,
  } as unknown as ChatApi & Record<string, ReturnType<typeof vi.fn>>;
  const onTranscript = vi.fn();
  const onBusyChange = vi.fn();
  const ui = (q = "dq_1") => <VoiceInput api={api} sessionId="ss_1" questionId={q} pollMs={5} onTranscript={onTranscript} onBusyChange={onBusyChange} {...props} />;
  const view = render(ui());
  return { api, onTranscript, onBusyChange, view, ui, user: userEvent.setup() };
}

let media: ReturnType<typeof installFakeMedia>;
beforeEach(() => { media = installFakeMedia(); });
afterEach(() => removeFakeMedia());

describe("browser capability helpers", () => {
  it("detects support, picks a recorder format, and formats the clock", () => {
    expect(voiceSupported()).toBe(true);
    expect(pickMimeType()).toBe("audio/webm;codecs=opus");
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(61_500)).toBe("1:01");
    removeFakeMedia();
    expect(voiceSupported()).toBe(false); // no MediaRecorder / microphone API
    expect(pickMimeType()).toBeUndefined();
  });
});

describe("recording a voice answer", () => {
  it("records, uploads for the current question, polls the job, and hands back the transcript", async () => {
    const { api, onTranscript, user } = setup({
      getVoiceNote: vi.fn().mockResolvedValueOnce(note("running")).mockResolvedValue(note("done", { transcript: "he wants whatsapp" })),
    });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    expect(await screen.findByText(/Recording 0:00/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("he wants whatsapp", "vn_1"));
    const [sid, qid, blob, ms] = (api.uploadVoice as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect([sid, qid]).toEqual(["ss_1", "dq_1"]);
    expect((blob as Blob).type).toBe("audio/webm;codecs=opus");
    expect((blob as Blob).size).toBe(7);
    expect(typeof ms).toBe("number");
    expect(api.getVoiceNote).toHaveBeenCalledWith("ss_1", "vn_1");
    expect(media.trackStop).toHaveBeenCalled(); // the microphone is released
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
  });

  it("stops by itself at the time limit", async () => {
    const { api, onTranscript, user } = setup({}, { maxMs: 60 });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await waitFor(() => expect(api.uploadVoice).toHaveBeenCalled());
    await waitFor(() => expect(onTranscript).toHaveBeenCalled());
  });

  it("cancelling a recording uploads nothing and frees the microphone", async () => {
    const { api, user } = setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(api.uploadVoice).not.toHaveBeenCalled();
    expect(media.trackStop).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
  });

  it("explains a blocked microphone and does not start recording", async () => {
    removeFakeMedia();
    media = installFakeMedia({ denied: true });
    const { api, user } = setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Microphone access was blocked/);
    expect(FakeRecorder.instances).toHaveLength(0);
    expect(api.uploadVoice).not.toHaveBeenCalled();
  });

  it("reports an empty recording instead of uploading it", async () => {
    const { api, user } = setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await screen.findByRole("button", { name: "Stop" });
    FakeRecorder.instances[0].emptyRecording = true;
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nothing was recorded/);
    expect(api.uploadVoice).not.toHaveBeenCalled();
  });

  it("shows upload errors and lets the agent record again", async () => {
    const { user } = setup({ uploadVoice: vi.fn().mockRejectedValue(new ApiError(413, "recording too large")) });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("recording too large");
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Retry transcription" })).not.toBeInTheDocument(); // nothing to retry
  });

  it("a failed transcription can be retried on the server", async () => {
    const { api, onTranscript, user } = setup({
      getVoiceNote: vi.fn().mockResolvedValue(note("done", { transcript: "second try", attempt: 2 })),
      uploadVoice: vi.fn().mockResolvedValue(note("failed", { error: "no speech detected in the recording" })),
    });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no speech detected");
    await user.click(screen.getByRole("button", { name: "Retry transcription" }));
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith("second try", "vn_1"));
    expect(api.retryVoiceNote).toHaveBeenCalledWith("ss_1", "vn_1");
  });

  it("gives up with a message if transcription never finishes", async () => {
    const { user } = setup({ getVoiceNote: vi.fn().mockResolvedValue(note("running")) }, { maxPolls: 3 });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/taking too long/);
  });

  it("moving to another question abandons the recording", async () => {
    const { api, view, ui, user } = setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await screen.findByRole("button", { name: "Stop" });
    view.rerender(ui("dq_2"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument());
    expect(FakeRecorder.instances[0].state).toBe("inactive");
    expect(api.uploadVoice).not.toHaveBeenCalled();
    expect(media.trackStop).toHaveBeenCalled();
  });

  it("a transcript that arrives after the question changed is dropped", async () => {
    let release!: (n: VoiceNote) => void;
    const upload = vi.fn().mockReturnValue(new Promise<VoiceNote>((r) => (release = r)));
    const { onTranscript, view, ui, user } = setup({ uploadVoice: upload });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    view.rerender(ui("dq_2"));
    await act(async () => release(note("done", { transcript: "late words" })));
    expect(onTranscript).not.toHaveBeenCalled();
  });

  it("reports when it is busy so the composer can lock", async () => {
    const { onBusyChange, user } = setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await waitFor(() => expect(onBusyChange).toHaveBeenCalledWith(true));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  });
});
