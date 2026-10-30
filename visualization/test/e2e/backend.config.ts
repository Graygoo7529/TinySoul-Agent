import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "playwright/test";

const visualizationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** Real Agent/owner/HTTP/WS flows with only the model output scripted. */
export default defineConfig({
  testDir: "./",
  testMatch: ["chat-flow.pw.ts", "presentation.pw.ts"],
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./backend.global.ts",
  use: {
    baseURL: "http://127.0.0.1:5199",
    browserName: "chromium",
  },
  webServer: {
    cwd: visualizationRoot,
    command: "pnpm exec vite --port 5199 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5199/",
    timeout: 120_000,
    reuseExistingServer: process.env.TINYSOUL_E2E_REUSE_SERVER === "1",
  },
  outputDir: "../../.local-test/playwright-output-backend",
});
