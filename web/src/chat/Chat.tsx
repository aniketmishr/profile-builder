import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type ChatApi } from "../api";
import { notifyParent } from "../embed";
import type { ConfirmResult, DebriefMessage, DebriefState, Decision, Extraction } from "../types";
import { humanize, valueToText } from "./decisions";
import { Review } from "./Review";
import { VoiceInput } from "./VoiceInput";
import { voiceSupported } from "./voice";

interface Props {
  sessionId: string;
  api: ChatApi;
  pollMs?: number;
  maxPolls?: number;
}

const errText = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

function bubbleText(m: DebriefMessage): string {
  if (m.role === "agent" && m.action === "skip") return "Skipped";
  if (m.role === "agent" && m.action === "end") return "Ended the debrief";
  return m.text;
}

export function Chat({ sessionId, api, pollMs = 1500, maxPolls = 40 }: Props) {
  const [debrief, setDebrief] = useState<DebriefState | null>(null);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null); // the answer being sent, shown right away
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [voice, setVoice] = useState<{ noteId: string; questionId: string } | null>(null); // transcript now in the box
  const [voiceBusy, setVoiceBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDebrief(await api.startDebrief(sessionId)); // idempotent: also resumes after a reload
    } catch (e) {
      setError(errText(e));
    }
  }, [api, sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [debrief?.messages.length, pending]);

  const currentQuestionId = debrief?.current_question_id ?? null;
  useEffect(() => {
    setVoice(null); // a transcript belongs to the question it was recorded for
  }, [currentQuestionId]);

  async function submit(action: "answer" | "skip" | "end") {
    if (!debrief?.current_question_id || busy) return;
    const sent = text.trim();
    if (action === "answer" && !sent) return;
    setBusy(true);
    setError(null);
    setConfirmEnd(false);
    if (action === "answer") setPending(sent);
    const voiceNoteId = action === "answer" && voice?.questionId === debrief.current_question_id ? voice.noteId : undefined;
    try {
      const next = await api.answer(sessionId, {
        question_id: debrief.current_question_id,
        action,
        ...(action === "answer" ? { text: sent } : {}),
        ...(voiceNoteId ? { voice_note_id: voiceNoteId } : {}),
      });
      setDebrief(next);
      setText("");
      setVoice(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The question moved on (double click, another tab). Show the truth instead of failing.
        try {
          setDebrief(await api.getDebrief(sessionId));
        } catch {
          /* the next action will surface the error */
        }
        setError("That question was already handled, so I've shown the latest state.");
        setText("");
      } else {
        setError(errText(e)); // the typed text stays in the box so nothing is lost
      }
    } finally {
      setPending(null);
      setBusy(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit("answer");
    }
  }

  if (!debrief) {
    return (
      <main className="chat">
        <p className="muted center">{error ? "" : "Getting your debrief ready…"}</p>
        {error && (
          <div className="center">
            <p className="error" role="alert">{error}</p>
            <button className="primary" onClick={() => void load()}>Try again</button>
          </div>
        )}
      </main>
    );
  }

  const active = debrief.state === "active";
  const canRecord = active && debrief.voice_enabled && voiceSupported() && debrief.current_question_id !== null;
  return (
    <main className="chat">
      <header className="chat-head">
        <strong>Quick debrief</strong>
        {active && (
          <span className="muted">
            Question {debrief.progress.asked} of up to {debrief.progress.cap}
          </span>
        )}
      </header>

      <div className="messages" aria-live="polite">
        {debrief.messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}${m.action === "skip" || m.action === "end" ? " quiet" : ""}`}>
            {bubbleText(m)}
          </div>
        ))}
        {pending && <div className="bubble agent">{pending}</div>}
        {busy && <div className="bubble ai quiet">…</div>}
        {debrief.state === "complete" && (
          <Summary api={api} sessionId={sessionId} pollMs={pollMs} maxPolls={maxPolls} />
        )}
        <div ref={bottom} />
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      {active && (
        <footer className="composer">
          {canRecord && (
            <VoiceInput
              api={api}
              sessionId={sessionId}
              questionId={debrief.current_question_id!}
              disabled={busy}
              pollMs={Math.min(pollMs, 1000)}
              onBusyChange={setVoiceBusy}
              onTranscript={(t, noteId) => {
                setText(t);
                setVoice({ noteId, questionId: debrief.current_question_id! });
              }}
            />
          )}
          <textarea
            aria-label="Your answer"
            placeholder={canRecord ? "Type a few words, or record a voice note…" : "Type a few words…"}
            value={text}
            rows={2}
            disabled={busy || voiceBusy}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
          />
          {voice?.questionId === debrief.current_question_id && (
            <p className="muted small">Transcribed from your voice note. Check it and fix anything, then send.</p>
          )}
          <div className="actions">
            <button className="primary" disabled={busy || voiceBusy || !text.trim()} onClick={() => void submit("answer")}>
              Send
            </button>
            <button disabled={busy} onClick={() => void submit("skip")}>Skip</button>
            {confirmEnd ? (
              <>
                <button className="danger" disabled={busy} onClick={() => void submit("end")}>End now</button>
                <button className="link" onClick={() => setConfirmEnd(false)}>Keep going</button>
              </>
            ) : (
              <button className="link" disabled={busy} onClick={() => setConfirmEnd(true)}>End debrief</button>
            )}
          </div>
        </footer>
      )}
    </main>
  );
}

/** After the debrief: wait for extraction, review, save. Safe to reload at any point. */
function Summary({ api, sessionId, pollMs, maxPolls }: { api: ChatApi; sessionId: string; pollMs: number; maxPolls: number }) {
  const [ex, setEx] = useState<Extraction | null>(null);
  const [saved, setSaved] = useState<ConfirmResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const [round, setRound] = useState(0); // bump to restart polling (retry)

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    setSlow(false);

    async function tick() {
      try {
        let e: Extraction;
        try {
          e = await api.getExtraction(sessionId);
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 404)) throw err;
          e = await api.startExtraction(sessionId); // none yet: start it ourselves
        }
        if (cancelled) return;
        setEx(e);
        setError(null);
        if (e.status === "running") {
          if (++polls >= maxPolls) setSlow(true);
          else timer = setTimeout(tick, pollMs);
        }
      } catch (err) {
        if (!cancelled) setError(errText(err));
      }
    }
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, sessionId, pollMs, maxPolls, round]);

  async function retry() {
    setBusy(true);
    try {
      setEx(await api.startExtraction(sessionId));
      setRound((r) => r + 1);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function save(decisions: Decision[]) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.confirm(sessionId, decisions);
      setSaved(result);
      notifyParent({ type: "profile-builder:saved", session_id: sessionId, saved: result.saved.length + result.unchanged.length, discarded: result.discarded });
      setEx(await api.getExtraction(sessionId));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setRound((r) => r + 1); // already saved elsewhere: refresh
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !ex) {
    return (
      <div className="card">
        <p className="error" role="alert">{error}</p>
        <button onClick={() => setRound((r) => r + 1)}>Try again</button>
      </div>
    );
  }
  if (!ex || ex.status === "running") {
    return (
      <div className="card">
        <p className="muted">{slow ? "This is taking longer than expected." : "Preparing your summary…"}</p>
        {slow && <button disabled={busy} onClick={() => void retry()}>Try again</button>}
      </div>
    );
  }
  if (ex.status === "failed") {
    return (
      <div className="card">
        <p className="error" role="alert">I couldn't prepare the summary.</p>
        <button disabled={busy} onClick={() => void retry()}>Try again</button>
      </div>
    );
  }
  if (ex.status === "confirmed") {
    const savedFacts = ex.facts.filter((f) => f.status === "saved");
    return (
      <div className="card done">
        <h2>Saved ✓</h2>
        <p className="muted">
          {savedFacts.length === 0 ? "Nothing was added to the profile." : `${savedFacts.length} fact${savedFacts.length === 1 ? "" : "s"} added to the profile.`}
        </p>
        <ul className="saved">
          {savedFacts.map((f) => (
            <li key={f.id}><strong>{humanize(f.key)}:</strong> {valueToText(f.value)}</li>
          ))}
        </ul>
        {saved && saved.discarded > 0 && <p className="muted">{saved.discarded} discarded.</p>}
      </div>
    );
  }
  return <Review extraction={ex} busy={busy} error={error} onSave={(d) => void save(d)} />;
}
