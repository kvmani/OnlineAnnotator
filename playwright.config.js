import { defineConfig, devices } from "@playwright/test";

/*
 * End-to-end journeys through a real browser against a throw-away demo server.
 *
 * `OA_BASE_URL` points the suite at a server that is already running and suppresses
 * the managed one. Otherwise a fresh demo server is started on port 5072 with an
 * empty data directory, so every run starts from the same known state.
 */
const baseURL = process.env.OA_BASE_URL ?? "http://127.0.0.1:5072";

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  timeout: 60_000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: process.env.OA_BASE_URL
    ? undefined
    : {
        command:
          'python -c "import shutil; shutil.rmtree(\'.e2e-data\', ignore_errors=True)" && ' +
          "python -m online_annotator serve --demo --host 127.0.0.1 --port 5072 --data-dir .e2e-data",
        env: { PYTHONPATH: "src", ONLINE_ANNOTATOR_LOGIN_ATTEMPTS_PER_15MIN: "50", ONLINE_ANNOTATOR_PORTAL_URL: ":5000/" },
        url: "http://127.0.0.1:5072/api/health",
        reuseExistingServer: false,
        timeout: 60_000,
      },
});
