import { defineConfig, devices } from "@playwright/test";

const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: externalBaseUrl ?? "http://127.0.0.1:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } }
  ],
  webServer: externalBaseUrl
    ? undefined
    : {
        command: "npm run dev",
        url: "http://127.0.0.1:3001/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          API_INTERNAL_URL: "http://127.0.0.1:8999",
          PROMOTION_UI_FIXTURE_FALLBACK: "1"
        }
      }
});
