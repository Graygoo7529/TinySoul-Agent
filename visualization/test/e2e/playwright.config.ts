import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "playwright/test";

const visualizationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * Dev-only verification entries: the Mermaid/TikZJax code block renderers
 * (W2) and the F1-D minimal real interaction flow against a real Endpoint.
 * Run from visualization/:
 *   pnpm exec playwright test -c test/e2e/playwright.config.ts
 *
 * The `.pw.ts` suffix keeps these specs out of the vitest default include
 * pattern (`*.test.*` / `*.spec.*`).
 */
export default defineConfig({
  testDir: "./",
  testMatch: "**/*.pw.ts",
  timeout: 240_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  // Real backend harness (real Agent + Endpoint, scripted model) for the
  // chat-flow spec; publishes <repo>/.local-test/e2e-backend/connection.json.
  // The setup returns its own teardown function.
  globalSetup: "./backend.global.ts",
  use: {
    baseURL: "http://127.0.0.1:5199",
    browserName: "chromium",
  },
  webServer: {
    // Playwright spawns the server with cwd = this config's directory; vite
    // must run from the visualization root to serve codeblocks-dev.html.
    cwd: visualizationRoot,
    command: "pnpm exec vite --port 5199 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5199/codeblocks-dev.html",
    timeout: 120_000,
    reuseExistingServer: false,
  },
  // Keep run artifacts inside the repo-ignored .local-test tree.
  outputDir: "../../.local-test/playwright-output",
});
