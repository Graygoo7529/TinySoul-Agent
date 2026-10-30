import { mkdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "playwright/test";

/** Representative screenshots for human review against the real backend harness. */
const here = path.dirname(fileURLToPath(import.meta.url));
const connectionFile = path.resolve(here, "../../../.local-test/e2e-backend/connection.json");
const shotsDir = path.resolve(here, "../../.local-test/visual-review");
const BACKEND_WAIT = 30_000;
const MIN_PNG_BYTES = 15_000;

interface BackendConnection {
  address: string;
  token: string;
}

function backendConnection(): BackendConnection {
  return JSON.parse(readFileSync(process.env.TINYSOUL_E2E_CONNECTION ?? connectionFile, "utf-8")) as BackendConnection;
}

async function shot(page: Page, name: string, ready: Locator, waitForIdle = true): Promise<void> {
  await test.step(name, async () => {
    await expect(ready).toBeVisible({ timeout: BACKEND_WAIT });
    if (waitForIdle) await expect(page.locator("main .animate-spin-slow:visible")).toHaveCount(0, { timeout: BACKEND_WAIT });
    if (await ready.evaluate((element) => element.classList.contains("answer-card"))) {
      await expect.poll(() => ready.evaluate((element) => ({
        card: getComputedStyle(element).opacity,
        terminal: getComputedStyle(element, "::after").opacity,
      }))).toEqual({ card: "1", terminal: "0" });
    }
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    });
    const file = path.join(shotsDir, `${name}.png`);
    await page.screenshot({ path: file });
    const size = statSync(file).size;
    expect(size, `${name}.png looks blank (${size} bytes)`).toBeGreaterThan(MIN_PNG_BYTES);
  });
}

async function connect(page: Page): Promise<void> {
  const { address, token } = backendConnection();
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(address);
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Start a conversation")).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(page.getByTitle("Workspace", { exact: true })).toBeEnabled();
}

test("representative page visual review", async ({ page }) => {
  test.setTimeout(300_000);
  mkdirSync(shotsDir, { recursive: true });
  const runId = Date.now().toString(36);
  const plainText = `e2e-plain visual review ${runId}`;
  const askText = `e2e-ask visual review ${runId}`;
  const commentText = `e2e-reply-comment visual ${runId}`;
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await connect(page);
  await shot(page, "01-chat-empty-light", page.getByText("Start a conversation"));

  const composer = page.getByPlaceholder("Message TinySoul…");
  await composer.fill(plainText);
  await composer.press("Enter");
  const firstAnswer = page.locator(".answer-card", { hasText: `You said: ${plainText}.` });
  await expect(firstAnswer).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-streaming, .answer-settling")).toHaveCount(0, { timeout: BACKEND_WAIT });
  await shot(page, "02-chat-answer-light", firstAnswer);

  await composer.fill(askText);
  await composer.press("Enter");
  const dock = page.getByRole("dialog", { name: "Waiting for your reply" });
  const question = dock.getByText("Which option do you pick?", { exact: true });
  await expect(question).toBeVisible({ timeout: BACKEND_WAIT });
  await shot(page, "03-chat-question-light", question, false);

  await page.getByRole("button", { name: "Context", exact: true }).click();
  const drawer = page.locator('aside[role="dialog"]').first();
  await shot(page, "04-context-overview-light", drawer.locator("section").first(), false);
  await drawer.locator("section button").first().click();
  await shot(page, "05-context-segment-light", page.getByRole("button", { name: "Back", exact: true }), false);
  await drawer.getByRole("button", { name: "Close", exact: true }).click();
  await expect(drawer).toHaveCount(0);

  await dock.locator("label", { hasText: "Option B" }).click();
  await dock.getByPlaceholder("Additional thoughts (optional)…").fill(commentText);
  await dock.getByRole("button", { name: "Reply" }).click();
  const finalAnswer = page.locator(".answer-card", { hasText: "You picked Option B (opt_b)." });
  await expect(finalAnswer).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator('[data-question-form="readonly"]')).toContainText(commentText);
  await expect(page.locator(".answer-streaming, .answer-settling")).toHaveCount(0, { timeout: BACKEND_WAIT });
  await page.getByTitle("Switch to dark theme", { exact: true }).click();
  await page.reload();
  await expect(page.locator(".answer-card")).toHaveCount(2, { timeout: BACKEND_WAIT });
  await shot(page, "06-chat-conversation-dark", finalAnswer);
  await page.getByTitle("Switch to light theme", { exact: true }).click();

  await page.getByRole("button", { name: "History", exact: true }).click();
  const history = page.getByRole("dialog", { name: "History", exact: true });
  await shot(page, "08-history-days-light", history.getByRole("button", { name: "Session map of this day" }).first());
  await history.getByRole("button", { name: "Session map of this day" }).first().click();
  const sessionMap = page.getByRole("dialog", { name: "Session map", exact: true });
  await shot(page, "09-history-session-map-light", sessionMap.getByRole("heading", { name: "Session map" }));
  await sessionMap.getByRole("button", { name: "Close", exact: true }).click();

  await page.getByTitle("Settings", { exact: true }).click();
  await shot(page, "10-settings-overview-light", page.locator("h1", { hasText: "配置状态" }));
  await page.getByRole("button", { name: "LLM 模型", exact: true }).click();
  await shot(page, "11-settings-llm-models-light", page.locator("h1", { hasText: "LLM 模型" }));
  await page.getByRole("button", { name: "Actions 与模型用途", exact: true }).click();
  await shot(page, "12-settings-actions-light", page.locator("h1", { hasText: "Actions 与模型用途" }));
  await page.getByRole("button", { name: "运行方案", exact: true }).click();
  await shot(page, "13-settings-plans-light", page.locator("h1", { hasText: "运行方案" }));

  await page.getByTitle("Home", { exact: true }).click();
  await expect(page.getByText("What the next run uses")).toBeVisible();
  await page.getByRole("button", { name: "Actual", exact: true }).click();
  const homeEntry = page.locator('main button[title^="home:"]').first();
  await expect(homeEntry).toBeVisible({ timeout: BACKEND_WAIT });
  await homeEntry.click();
  await shot(page, "14-home-actual-light", page.locator("main .md-body:visible").first());

  await page.getByTitle("Memory", { exact: true }).click();
  await shot(page, "15-memory-active-light", page.getByText("What the agent is recording this day — read-only here.", { exact: true }));
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  const filter = page.getByLabel("Filter knowledge");
  await expect(filter).toBeVisible({ timeout: BACKEND_WAIT });
  const memoryDoc = page.locator('main button[title^="memory:"]').first();
  if (await memoryDoc.count()) {
    await memoryDoc.click();
    await expect(page.locator("main .md-body:visible").first()).toBeVisible({ timeout: BACKEND_WAIT });
  }
  await shot(page, "16-memory-knowledge-light", filter);

  await page.getByTitle("Workspace", { exact: true }).click();
  const baseline = page.getByText("baseline.md", { exact: true }).first();
  await expect(baseline).toBeVisible({ timeout: BACKEND_WAIT });
  await baseline.click();
  await shot(page, "17-workspace-light", page.getByRole("heading", { name: "Baseline read", exact: true }));

  await page.getByTitle("Runtime", { exact: true }).click();
  await shot(page, "18-runtime-execution-light", page.getByRole("button", { name: "Execution", exact: true }));
  await page.getByRole("button", { name: "Jobs", exact: true }).click();
  await shot(page, "19-runtime-jobs-light", page.getByRole("button", { name: "Jobs", exact: true }));
  await page.getByRole("button", { name: "MCP", exact: true }).click();
  await shot(page, "20-runtime-mcp-light", page.getByRole("button", { name: "MCP", exact: true }));

  await page.setViewportSize({ width: 800, height: 900 });
  await page.getByTitle("Chat", { exact: true }).click();
  await expect(page.locator(".answer-card")).toHaveCount(2, { timeout: BACKEND_WAIT });
  await shot(page, "21-chat-narrow-800-light", finalAnswer);
  await page.getByTitle("Settings", { exact: true }).click();
  await page.getByRole("button", { name: "设置页面", exact: true }).click();
  await page.getByRole("button", { name: "配置状态", exact: true }).click();
  await shot(page, "22-settings-narrow-800-light", page.locator("h1", { hasText: "配置状态" }));

  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});
