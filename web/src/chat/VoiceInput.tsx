import { useEffect, useRef, useState } from "react";
import type { ChatApi } from "../api";
import type { VoiceNote } from "../types";
import { formatClock, pickMimeType } from "./voice";

interface Props {
  api: ChatApi;
  sessionId: string;
  questionId: string;
  disabled?: boolean;
  maxMs?: number; // recording limit (the server allows a little more)
  pollMs?: number;
  maxPolls?: number;
  onTranscript: (text: string, noteId: string) => void;
  onBusyChange?: (busy: boolean) => void;
}

type Phase = "idle" | "recording" | "uploading" | "transcribing" | "failed";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

/** Record a short voice answer, upload it, wait for the transcript (a background job on the server),
 *  and hand the text back so the agent can edit it before sending. */
export function VoiceInput({ api, sessionId, questionId, disabled, maxMs = 60_000, pollMs = 1000, maxPolls = 90, onTranscript, onBusyChange }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [failedNote, setFailedNote] = useState<string | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const timers = useRef<{ tick?: ReturnType<typeof setInterval>; stop?: ReturnType<typeof setTimeout> }>({});
  const run = useRef(0); // bumped to abandon whatever is in flight (cancel, new question, unmount)

  function releaseMic() {
    clearInterval(timers.current.tick);
    clearTimeout(timers.current.stop);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }

  function abandon() {
    run.current++;
    const r = recorder.current;
    recorder.current = null;
    if (r && r.state !== "inactive") r.stop(); // its onstop sees the bumped run and does nothing
    releaseMic();
  }

  // A different question means any recording or transcription in progress no longer applies.
  useEffect(() => {
    setPhase("idle");
    setError(null);
    setFailedNote(null);
    return abandon;
  }, [questionId]);

  useEffect(() => {
    onBusyChange?.(phase === "recording" || phase === "uploading" || phase === "transcribing");
  }, [phase, onBusyChange]);

  function fail(message: string, noteId: string | null) {
    setError(message);
    setFailedNote(noteId);
    setPhase("failed");
  }

  async function track(first: VoiceNote, myRun: number) {
    setPhase("transcribing");
    let note = first;
    for (let i = 0; i < maxPolls; i++) {
      if (note.status === "done") {
        setPhase("idle");
        onBusyChange?.(false); // unlock the composer in the same update that fills it, never one render later
        onTranscript(note.transcript ?? "", note.id);
        return;
      }
      if (note.status === "failed") return fail(note.error ?? "I couldn't transcribe that recording.", note.id);
      await sleep(pollMs);
      if (run.current !== myRun) return;
      note = await api.getVoiceNote(sessionId, note.id);
      if (run.current !== myRun) return;
    }
    fail("Transcription is taking too long.", note.id);
  }

  async function send(blob: Blob, durationMs: number, myRun: number) {
    if (blob.size === 0) return fail("Nothing was recorded. Check your microphone and try again.", null);
    setPhase("uploading");
    try {
      const note = await api.uploadVoice(sessionId, questionId, blob, durationMs);
      if (run.current === myRun) await track(note, myRun);
    } catch (e) {
      if (run.current === myRun) fail(errText(e), null);
    }
  }

  async function start() {
    setError(null);
    setFailedNote(null);
    const myRun = ++run.current;
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked. Allow it in your browser, or type your answer instead.");
      return;
    }
    if (run.current !== myRun) {
      media.getTracks().forEach((t) => t.stop());
      return;
    }
    stream.current = media;
    const mime = pickMimeType();
    const rec = new MediaRecorder(media, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.current.push(e.data);
    };
    rec.onstop = () => {
      releaseMic();
      if (run.current !== myRun) return; // cancelled or superseded
      const blob = new Blob(chunks.current, { type: rec.mimeType || mime || "audio/webm" });
      void send(blob, Date.now() - startedAt.current, myRun);
    };
    recorder.current = rec;
    startedAt.current = Date.now();
    rec.start();
    setElapsed(0);
    setPhase("recording");
    timers.current.tick = setInterval(() => setElapsed(Date.now() - startedAt.current), 250);
    timers.current.stop = setTimeout(stop, maxMs); // never record longer than the limit
  }

  function stop() {
    clearInterval(timers.current.tick);
    clearTimeout(timers.current.stop);
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
  }

  function cancel() {
    abandon();
    setPhase("idle");
  }

  async function retry() {
    if (!failedNote) return;
    const myRun = ++run.current;
    setError(null);
    setPhase("transcribing");
    try {
      await track(await api.retryVoiceNote(sessionId, failedNote), myRun);
    } catch (e) {
      if (run.current === myRun) fail(errText(e), null);
    }
  }

  return (
    <div className="voice">
      {phase === "recording" && (
        <>
          <span className="rec" role="status">● Recording {formatClock(elapsed)} / {formatClock(maxMs)}</span>
          <button className="primary" onClick={stop}>Stop</button>
          <button className="link" onClick={cancel}>Cancel</button>
        </>
      )}
      {(phase === "uploading" || phase === "transcribing") && (
        <>
          <span className="muted" role="status">Transcribing your voice note…</span>
          <button className="link" onClick={cancel}>Cancel</button>
        </>
      )}
      {(phase === "idle" || phase === "failed") && (
        <>
          <button aria-label="Record a voice note" disabled={disabled} onClick={() => void start()}>🎤 Record</button>
          {phase === "failed" && failedNote && <button onClick={() => void retry()}>Retry transcription</button>}
        </>
      )}
      {error && <span className="error inline" role="alert">{error}</span>}
    </div>
  );
}
