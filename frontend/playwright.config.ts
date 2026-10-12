import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5183",
    headless: true,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  },
  reporter: "list",
  webServer: {
    command: "npm run dev -- --port 5183",
    url: "http://127.0.0.1:5183",
    reuseExistingServer: false,
    env: { JOBPILOT_API_TARGET: "http://127.0.0.1:8001" },
    timeout: 30000,
  },
});
