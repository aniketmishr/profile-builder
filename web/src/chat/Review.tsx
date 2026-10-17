import { useState } from "react";
import type { Decision, Extraction } from "../types";
import { buildDecisions, confidenceLabel, emptyKeptFacts, humanize, valueToText } from "./decisions";

interface Props {
  extraction: Extraction;
  busy: boolean;
  error: string | null;
  onSave: (decisions: Decision[]) => void;
}

/** The "here's what I'll save (edit anything)" step. */
export function Review({ extraction, busy, error, onSave }: Props) {
  const { facts } = extraction;
  const [texts, setTexts] = useState<Record<string, string>>(
    () => Object.fromEntries(facts.map((f) => [f.id, valueToText(f.value)])),
  );
  const [discarded, setDiscarded] = useState<Set<string>>(new Set());
  const [showErrors, setShowErrors] = useState(false);

  const edits = { texts, discarded };
  const empty = new Set(emptyKeptFacts(facts, edits));
  const kept = facts.length - discarded.size;

  function toggle(id: string) {
    setDiscarded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function save() {
    if (empty.size > 0) {
      setShowErrors(true);
      return;
    }
    onSave(buildDecisions(facts, edits));
  }

  return (
    <section className="review" aria-label="Review before saving">
      <h2>Here's what I'll save</h2>
      {extraction.source === "fallback" && (
        <p className="notice">
          The AI summary wasn't available, so these are your own words saved as notes. Edit or discard anything.
        </p>
      )}
      {facts.length === 0 ? (
        <p className="muted">Nothing to save from this debrief.</p>
      ) : (
        <ul className="facts">
          {facts.map((f) => {
            const off = discarded.has(f.id);
            return (
              <li key={f.id} className={off ? "fact discarded" : "fact"}>
                <div className="fact-head">
                  <span className="fact-label">
                    {humanize(f.category)} · {humanize(f.key)}
                  </span>
                  <span className={`badge ${confidenceLabel(f.confidence).toLowerCase()}`}>
                    {confidenceLabel(f.confidence)}
                  </span>
                </div>
                <input
                  aria-label={`Value for ${humanize(f.key)}`}
                  value={texts[f.id]}
                  disabled={off || busy}
                  onChange={(e) => setTexts((t) => ({ ...t, [f.id]: e.target.value }))}
                />
                {showErrors && empty.has(f.id) && (
                  <p className="field-error">The value can't be empty. Discard the fact instead.</p>
                )}
                <p className="evidence">You said: “{f.evidence}”</p>
                <button type="button" className="link" disabled={busy} onClick={() => toggle(f.id)}>
                  {off ? "Restore" : "Discard"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <button type="button" className="primary" disabled={busy} onClick={save}>
        {busy ? "Saving…" : facts.length === 0 || kept === 0 ? "Finish" : `Save ${kept} fact${kept === 1 ? "" : "s"}`}
      </button>
    </section>
  );
}
