import { defineConfig } from "@playwright/test";

const PORT = 8765;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: process.env.SCREENSHOTS ? [] : ["**/screenshots.spec.ts"],
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: `uv run uvicorn api.main:app --port ${PORT}`,
    env: { VENTURETASTE_FIXTURES: "1" },
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
