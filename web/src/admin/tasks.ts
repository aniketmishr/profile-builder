// Mock "closed tasks" an admin panel would show. Different task types lead to different debrief questions.
export interface MockTask {
  id: string;
  type: string;
  title: string;
  outcome: string;
  channel: string;
  duration_sec: number;
  transcript_excerpt: string;
  agent: { id: string; name: string };
  end_user: { id: string; display_name: string };
  locale: string;
}

export const TASKS: MockTask[] = [
  {
    id: "task_8f3a21", type: "refund_dispute", title: "Refund for damaged order #44871",
    outcome: "resolved_partial_refund", channel: "whatsapp", duration_sec: 740,
    transcript_excerpt: "...I keep getting emails but I never read them, just WhatsApp me... ...my wife uses the account more than I do...",
    agent: { id: "ag_104", name: "Priya S." }, end_user: { id: "eu_55021", display_name: "Rahul M." }, locale: "en-IN",
  },
  {
    id: "task_9b1c07", type: "customer_onboarding", title: "Set up a new business account",
    outcome: "account_setup_complete", channel: "email", duration_sec: 1260,
    transcript_excerpt: "...I'm not very technical, please explain it step by step... Hindi is easier for me...",
    agent: { id: "ag_105", name: "Dev K." }, end_user: { id: "eu_55022", display_name: "Meera T." }, locale: "en-IN",
  },
  {
    id: "task_a4d9e2", type: "troubleshooting", title: "App keeps crashing on launch",
    outcome: "resolved_reinstall", channel: "chat", duration_sec: 540,
    transcript_excerpt: "...it only crashes on my old phone... I was really annoyed, this is the third time...",
    agent: { id: "ag_105", name: "Dev K." }, end_user: { id: "eu_77001", display_name: "Jo R." }, locale: "en-IN",
  },
  {
    id: "task_c7e5f0", type: "booking_change", title: "Move delivery slot for order #45102",
    outcome: "rescheduled", channel: "whatsapp", duration_sec: 210,
    transcript_excerpt: "...mornings only please, I'm out after noon...",
    agent: { id: "ag_104", name: "Priya S." }, end_user: { id: "eu_55021", display_name: "Rahul M." }, locale: "en-IN",
  },
];
