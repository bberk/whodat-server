import { defineConfig } from "@playwright/test";

const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 4173);
const apiPort = Number(process.env.E2E_API_PORT ?? 8000);
const frontendUrl = `http://localhost:${frontendPort}`;
const apiUrl = `http://localhost:${apiPort}`;

/**
 * End-to-end suite for the critical journey and the accessibility checks.
 *
 * Two servers are started unless they are already running: the backend script applies migrations,
 * seeds deterministic data, and serves the API; the frontend is built and served by `vite preview`.
 * The suite is deliberately serial because the journey writes accounts against one shared database.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: "test-results",
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "mobile-360",
      use: { browserName: "chromium", viewport: { width: 360, height: 800 } },
    },
    {
      name: "tablet-768",
      use: { browserName: "chromium", viewport: { width: 768, height: 1024 } },
    },
    {
      name: "desktop-1280",
      use: { browserName: "chromium", viewport: { width: 1280, height: 900 } },
    },
  ],
  webServer: [
    {
      command: `CORS_ORIGINS=${frontendUrl} E2E_API_PORT=${apiPort} ../e2e/start-backend.sh`,
      url: `${apiUrl}/health`,
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `VITE_API_BASE_URL=${apiUrl} pnpm build && pnpm preview --host localhost --port ${frontendPort} --strictPort`,
      url: frontendUrl,
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
