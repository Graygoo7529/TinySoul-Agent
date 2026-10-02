import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "playwright/test";

const visualizationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * F7-B visual review entry: representative-page screenshots against the real
 * backend harness (backend_server.py via the shared backend.global.ts), stored
 * under .local-test/visual-review/ for visual inspection.
 *
 * Deliberately a separate config from playwright.config.ts so the guarded e2e
 * pair (chat-flow / codeblocks) keeps its own scope; the default config
 * test-ignores this spec. Run from visualization/:
 *   TINYSOUL_PYTHON=<python> pnpm exec playwright test -c test/e2e/visual-review.config.ts
 */
export default defineConfig({
  testDir: "./",
  testMatch: "visual-review.pw.ts",
  timeout: 360_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./backend.global.ts",
  use: {
    baseURL: "http://127.0.0.1:5198",
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    cwd: visualizationRoot,
    command: "pnpm exec vite --port 5198 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5198/",
    timeout: 120_000,
    reuseExistingServer: process.env.TINYSOUL_E2E_REUSE_SERVER === "1",
  },
  outputDir: "../../.local-test/playwright-output-visual",
});
