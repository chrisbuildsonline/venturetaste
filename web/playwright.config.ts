import { defineConfig } from "@playwright/test";

const PORT = 8765;
// BASE_URL points the opt-in live spec at an already running deployment (docker:smoke, the public URL).
const BASE_URL = process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: [
    ...(process.env.SCREENSHOTS ? [] : ["**/screenshots.spec.ts"]),
    ...(BASE_URL ? ["**/diligence.spec.ts"] : ["**/live.spec.ts"]),
  ],
  use: { baseURL: BASE_URL ?? `http://127.0.0.1:${PORT}` },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: BASE_URL
    ? undefined
    : {
        command: `uv run uvicorn api.main:app --port ${PORT}`,
        env: { VENTURETASTE_FIXTURES: "1", VENTURETASTE_RATE_LIMIT: "100000" },
        cwd: "..",
        url: `http://127.0.0.1:${PORT}/api/health`,
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
});
