// A stand-in for the browser's microphone and MediaRecorder, so recording flows can be tested in jsdom.
import { vi } from "vitest";

export class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (t: string) => t === "audio/webm;codecs=opus";
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  emptyRecording = false;

  constructor(public stream: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "";
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    const bytes = this.emptyRecording ? [] : [0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3];
    this.ondataavailable?.({ data: new Blob([new Uint8Array(bytes)], { type: this.mimeType }) });
    this.onstop?.();
  }
}

export function installFakeMedia(opts: { denied?: boolean } = {}) {
  const trackStop = vi.fn();
  const getUserMedia = opts.denied
    ? vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"))
    : vi.fn().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] });
  FakeRecorder.instances = [];
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  return { getUserMedia, trackStop };
}

export function removeFakeMedia() {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
}
