import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: { "/v1": "http://localhost:8000", "/health": "http://localhost:8000" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/vitest-setup.ts"] },
});
