// Mirrors the API's response models (see /docs). Keep in sync with app/schemas.py.
export type FactValue = string | string[];

export interface DebriefMessage {
  id: string;
  seq: number;
  role: "ai" | "agent";
  text: string;
  question_id: string | null;
  action: string | null;
  created_at: string | null;
}

export interface DebriefQuestion {
  id: string;
  seq: number;
  category: string;
  text: string;
  kind: string;
  status: string;
}

export interface DebriefState {
  session_id: string;
  state: "not_started" | "active" | "complete";
  end_reason: string | null;
  plan_source: string | null;
  current_question_id: string | null;
  progress: { asked: number; cap: number };
  voice_enabled: boolean;
  questions: DebriefQuestion[];
  messages: DebriefMessage[];
}

export interface AnswerBody {
  question_id: string;
  action: "answer" | "skip" | "end";
  text?: string;
  voice_note_id?: string; // set when the text came from a voice note's transcript
}

export interface VoiceNote {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  question_id: string;
  transcript: string | null;
  error: string | null;
  attempt: number;
  size_bytes: number;
  duration_ms: number | null;
}

export interface ExtractedFact {
  id: string;
  category: string;
  key: string;
  value: FactValue;
  confidence: number;
  evidence: string;
  status: "proposed" | "saved" | "discarded";
  edited: boolean;
}

export interface Extraction {
  session_id: string;
  status: "running" | "ready" | "confirmed" | "failed";
  source: string | null;
  prompt_version: string | null;
  model: string | null;
  error: string | null;
  attempt: number;
  dropped_count: number;
  facts: ExtractedFact[];
}

export type Decision =
  | { fact_id: string; action: "keep" | "discard" }
  | { fact_id: string; action: "edit"; value: FactValue };

export interface Fact {
  id: string;
  category: string;
  key: string;
  value: FactValue;
  confidence: number;
  evidence: string | null;
  source_session_id: string;
  captured_at: string;
  is_current: boolean;
  superseded_by: string | null;
  provenance: Record<string, unknown> | null;
}

export interface ConfirmResult {
  saved: Fact[];
  unchanged: Fact[];
  discarded: number;
  profile_version: number;
}

export interface SessionOut {
  session_id: string;
  status: string;
  created: boolean;
  chat_url: string;
  tenant_id: string;
  agent_id: string;
  end_user_id: string;
  task_id: string;
}

export interface SessionCreateBody {
  idempotency_key: string;
  tenant_id: string;
  agent: { id: string; name: string };
  end_user: { id: string; display_name: string };
  task: Record<string, unknown> & { id: string; type: string };
  locale?: string;
}

export interface Profile {
  end_user_id: string;
  tenant_id: string;
  display_name: string;
  profile_version: number;
  updated_at: string | null;
  facts: Fact[];
}

export interface HistoryEntry {
  category: string;
  key: string;
  versions: Fact[];
}

export interface SessionRef {
  session_id: string;
  task_id: string;
  task_type: string | null;
  task_title: string | null;
  agent_id: string;
  created_at: string | null;
}

export interface History {
  end_user_id: string;
  history: HistoryEntry[];
  sessions: SessionRef[];
}

export interface ContextOut {
  context: string;
  approx_tokens: number;
  truncated: boolean;
}
