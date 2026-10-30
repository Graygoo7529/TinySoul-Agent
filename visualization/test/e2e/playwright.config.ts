import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "playwright/test";

const visualizationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/**
 * Browser-only verification: real rendering and Motion without an Agent.
 * Run from visualization/:
 *   pnpm exec playwright test -c test/e2e/playwright.config.ts
 */
export default defineConfig({
  testDir: "./",
  testMatch: ["codeblocks.pw.ts", "trail-motion.pw.ts"],
  timeout: 240_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
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
    reuseExistingServer: process.env.TINYSOUL_E2E_REUSE_SERVER === "1",
  },
  // Keep run artifacts inside the repo-ignored .local-test tree.
  outputDir: "../../.local-test/playwright-output",
});
