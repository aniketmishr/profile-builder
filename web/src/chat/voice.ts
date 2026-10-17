/** Browser capability checks for recording. Voice is offered only when the server enables it AND the browser can record. */
export function voiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function"
  );
}

// Chrome/Firefox/Edge record webm or ogg; Safari records mp4. The server identifies the real format itself.
const CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
}

export function formatClock(ms: number): string {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
