import type { Decision, ExtractedFact, FactValue } from "../types";

export function valueToText(v: FactValue): string {
  return Array.isArray(v) ? v.join(", ") : v;
}

/** Turn what the agent typed back into the fact's original shape (a list stays a list). */
export function textToValue(text: string, original: FactValue): FactValue {
  return Array.isArray(original)
    ? text.split(",").map((s) => s.trim()).filter(Boolean)
    : text.trim();
}

function sameValue(a: FactValue, b: FactValue): boolean {
  return Array.isArray(a) && Array.isArray(b)
    ? a.length === b.length && a.every((x, i) => x === b[i])
    : a === b;
}

export interface ReviewEdits {
  texts: Record<string, string>; // fact id -> what is currently in the input
  discarded: Set<string>;
}

/** Only changes are sent: the server keeps every fact you don't mention. */
export function buildDecisions(facts: ExtractedFact[], edits: ReviewEdits): Decision[] {
  const out: Decision[] = [];
  for (const f of facts) {
    if (edits.discarded.has(f.id)) {
      out.push({ fact_id: f.id, action: "discard" });
      continue;
    }
    const text = edits.texts[f.id];
    if (text === undefined) continue;
    const value = textToValue(text, f.value);
    if (!sameValue(value, f.value)) out.push({ fact_id: f.id, action: "edit", value });
  }
  return out;
}

/** Facts the agent kept but emptied: they must discard them instead. */
export function emptyKeptFacts(facts: ExtractedFact[], edits: ReviewEdits): string[] {
  return facts
    .filter((f) => !edits.discarded.has(f.id) && edits.texts[f.id] !== undefined)
    .filter((f) => {
      const v = textToValue(edits.texts[f.id], f.value);
      return Array.isArray(v) ? v.length === 0 : v === "";
    })
    .map((f) => f.id);
}

export function confidenceLabel(c: number): "High" | "Medium" | "Low" {
  return c >= 0.85 ? "High" : c >= 0.7 ? "Medium" : "Low";
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ");
}
